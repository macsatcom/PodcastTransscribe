"""Topic clustering over transcript chunks.

Architectural notes
-------------------
We cluster at the **chunk** level (not episode level) so a single episode that
spans multiple topics gets multiple topic assignments. Vectors are L2-normalized
so HDBSCAN's euclidean metric is monotonically equivalent to cosine distance.

We only cluster chunks whose ``embedding_model`` matches the current configured
model — mixing dimensions or embedding spaces produces meaningless geometry.
While a re-embed run is in progress, recently-changed chunks simply don't
participate until they're re-embedded.

Outputs:
    * ``TopicCluster.representative_chunks`` — JSONB list of
      ``{episode_id, podcast_id, chunk_id, text, start_time, end_time}``
      ordered by closeness to centroid (top 5).
    * ``EpisodeTopic`` rows — one per (topic, episode) deduped from the chunk
      assignments; ``score`` is the count of chunks from that episode in the
      cluster, normalized to [0, 1] over the cluster.
"""

import logging
import math
import uuid
from collections import defaultdict

import numpy as np
from sklearn.cluster import HDBSCAN
from sqlalchemy import delete, select

from app.database import async_session
from app.models.episode import Episode
from app.models.setting import Setting
from app.models.topic import EpisodeTopic, TopicCluster
from app.models.transcript import Transcript, TranscriptChunk
from app.services.embedder import DEFAULT_EMBEDDING_MODEL
from app.services.openrouter import OpenRouterClient, get_api_key

logger = logging.getLogger(__name__)

ABSOLUTE_MIN = 3
LABEL_MODEL = "openai/gpt-4o-mini"
REPRESENTATIVES_PER_CLUSTER = 5
LABEL_CONTEXT_CHARS = 2400


async def run_clustering():
    async with async_session() as session:
        model_setting = await session.get(Setting, "embedding_model")
        target_model = model_setting.value if model_setting else DEFAULT_EMBEDDING_MODEL

        rows = await session.execute(
            select(
                TranscriptChunk.id,
                TranscriptChunk.text,
                TranscriptChunk.start_time,
                TranscriptChunk.end_time,
                TranscriptChunk.embedding,
                Episode.id,
                Episode.podcast_id,
            )
            .join(Transcript, Transcript.id == TranscriptChunk.transcript_id)
            .join(Episode, Episode.id == Transcript.episode_id)
            .where(TranscriptChunk.embedding.is_not(None))
            .where(TranscriptChunk.embedding_model == target_model)
        )
        all_rows = rows.all()
        if len(all_rows) < ABSOLUTE_MIN:
            logger.info(
                "Clustering: too few chunks at target model %s (%d), skipping",
                target_model,
                len(all_rows),
            )
            return

        # Build aligned arrays.
        chunk_ids: list[uuid.UUID] = []
        chunk_texts: list[str] = []
        chunk_starts: list[float | None] = []
        chunk_ends: list[float | None] = []
        episode_ids: list[uuid.UUID] = []
        podcast_ids: list[uuid.UUID] = []
        vectors: list[np.ndarray] = []
        for row in all_rows:
            chunk_ids.append(row[0])
            chunk_texts.append(row[1])
            chunk_starts.append(row[2])
            chunk_ends.append(row[3])
            episode_ids.append(row[5])
            podcast_ids.append(row[6])
            vec = np.asarray(row[4], dtype=np.float32)
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            vectors.append(vec)

        matrix = np.stack(vectors)

        # Adaptive min_cluster_size — sqrt(N)/4 floored at ABSOLUTE_MIN.
        min_size = max(ABSOLUTE_MIN, int(math.sqrt(len(matrix)) / 4))
        hdbscan = HDBSCAN(min_cluster_size=min_size, metric="euclidean")
        labels = hdbscan.fit_predict(matrix)

        noise = int((labels == -1).sum())
        valid_label_set = sorted(set(int(label) for label in labels) - {-1})
        logger.info(
            "Clustering: %d chunks (model=%s), min_cluster_size=%d, %d clusters, %d noise",
            len(matrix),
            target_model,
            min_size,
            len(valid_label_set),
            noise,
        )

        # Wipe prior auto results.
        await session.execute(
            delete(EpisodeTopic).where(
                EpisodeTopic.topic_id.in_(select(TopicCluster.id).where(TopicCluster.source == "auto"))
            )
        )
        await session.execute(delete(TopicCluster).where(TopicCluster.source == "auto"))
        await session.flush()

        for label_id in valid_label_set:
            indices = np.where(labels == label_id)[0]
            cluster_vecs = matrix[indices]
            centroid = cluster_vecs.mean(axis=0)
            centroid_norm = np.linalg.norm(centroid)
            if centroid_norm > 0:
                centroid = centroid / centroid_norm

            # Pick representatives: chunks closest to centroid (highest cosine sim).
            sims = cluster_vecs @ centroid
            order = np.argsort(-sims)
            rep_indices = indices[order[:REPRESENTATIVES_PER_CLUSTER]]
            representatives = []
            for ridx in rep_indices:
                representatives.append(
                    {
                        "chunk_id": str(chunk_ids[ridx]),
                        "episode_id": str(episode_ids[ridx]),
                        "podcast_id": str(podcast_ids[ridx]),
                        "text": chunk_texts[ridx],
                        "start_time": chunk_starts[ridx],
                        "end_time": chunk_ends[ridx],
                    }
                )

            label_text = await _generate_label(session, representatives)

            topic = TopicCluster(
                label=label_text,
                embedding=centroid.tolist(),
                representative_chunks=representatives,
                source="auto",
            )
            session.add(topic)
            await session.flush()

            # Episode assignments — score = fraction of cluster's chunks from that episode.
            ep_counts: dict[uuid.UUID, int] = defaultdict(int)
            for idx in indices:
                ep_counts[episode_ids[idx]] += 1
            total_in_cluster = len(indices)
            for ep_id, count in ep_counts.items():
                session.add(
                    EpisodeTopic(
                        topic_id=topic.id,
                        episode_id=ep_id,
                        score=round(count / total_in_cluster, 4),
                    )
                )

        await session.commit()
        logger.info("Clustering: saved %d topics", len(valid_label_set))


async def _generate_label(session, representatives: list[dict]) -> str:
    if not representatives:
        return "Unnamed Topic"
    excerpts = "\n---\n".join(r["text"] for r in representatives)[:LABEL_CONTEXT_CHARS]
    try:
        api_key = await get_api_key(session)
        async with OpenRouterClient(api_key=api_key) as client:
            result = await client._post(
                "chat/completions",
                {
                    "model": LABEL_MODEL,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "You generate concise topic labels (2-5 words, Title Case) "
                                "from podcast transcript excerpts. Respond with ONLY the label."
                            ),
                        },
                        {
                            "role": "user",
                            "content": f"Generate a topic label for these excerpts:\n\n{excerpts}",
                        },
                    ],
                },
            )
            choices = result.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "")
                cleaned = content.strip().strip('"').strip("'")
                if cleaned:
                    return cleaned[:80]
    except Exception as exc:  # noqa: BLE001 — label is best-effort
        logger.warning("Label generation failed: %s", exc)
    return "Unnamed Topic"
