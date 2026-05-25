import logging
import uuid

import numpy as np
from sklearn.cluster import HDBSCAN
from sqlalchemy import delete, select

from app.database import async_session
from app.models.episode import Episode
from app.models.topic import EpisodeTopic, TopicCluster
from app.models.transcript import Transcript, TranscriptChunk
from app.services.openrouter import OpenRouterClient, get_api_key

logger = logging.getLogger(__name__)

CLUSTER_MIN_SIZE = 3


async def run_clustering():
    async with async_session() as session:
        rows = await session.execute(
            select(
                Episode.id,
                TranscriptChunk.embedding,
            )
            .join(Transcript, Transcript.episode_id == Episode.id)
            .join(TranscriptChunk, TranscriptChunk.transcript_id == Transcript.id)
            .where(TranscriptChunk.embedding.is_not(None))
        )
        all_rows = rows.all()
        if len(all_rows) < CLUSTER_MIN_SIZE:
            logger.info("Clustering: too few chunks with embeddings (%d), skipping", len(all_rows))
            return

        episode_chunks: dict[str, list[np.ndarray]] = {}
        for row in all_rows:
            eid = str(row[0])
            if eid not in episode_chunks:
                episode_chunks[eid] = []
            episode_chunks[eid].append(np.array(row[1], dtype=np.float32))

        episode_ids = []
        matrix_rows = []
        for eid, chunks in episode_chunks.items():
            episode_ids.append(eid)
            matrix_rows.append(np.mean(chunks, axis=0))

        matrix = np.stack(matrix_rows)

        hdbscan = HDBSCAN(min_cluster_size=CLUSTER_MIN_SIZE, metric="euclidean")
        labels = hdbscan.fit_predict(matrix)

        noise_count = int((labels == -1).sum())
        cluster_count = len(set(labels)) - (1 if -1 in labels else 0)
        logger.info("Clustering: %d episodes, %d clusters, %d noise", len(episode_ids), cluster_count, noise_count)

        await session.execute(
            delete(EpisodeTopic).where(
                EpisodeTopic.topic_id.in_(
                    select(TopicCluster.id).where(TopicCluster.source == "auto")
                )
            )
        )
        await session.execute(delete(TopicCluster).where(TopicCluster.source == "auto"))
        await session.flush()

        cluster_labels_set = sorted(set(labels) - {-1})
        for cluster_id in cluster_labels_set:
            indices = np.where(labels == cluster_id)[0]
            cluster_episode_ids = [episode_ids[i] for i in indices]
            cluster_matrix = matrix[indices]
            centroid = cluster_matrix.mean(axis=0)

            chunks_result = await session.execute(
                select(TranscriptChunk.text)
                .join(Transcript, Transcript.id == TranscriptChunk.transcript_id)
                .where(Transcript.episode_id.in_(cluster_episode_ids))
                .limit(20)
            )
            chunk_texts = [r[0] for r in chunks_result.all()]
            combined = " ".join(chunk_texts)[:3000]

            label = await _generate_label(session, combined)

            topic = TopicCluster(
                label=label,
                embedding=centroid.tolist(),
                source="auto",
            )
            session.add(topic)
            await session.flush()

            for ep_id in cluster_episode_ids:
                session.add(EpisodeTopic(
                    topic_id=topic.id,
                    episode_id=uuid.UUID(ep_id),
                    score=1.0,
                ))

        await session.commit()
        logger.info("Clustering: saved %d topics", cluster_count)


async def _generate_label(session, chunk_text: str) -> str:
    try:
        api_key = await get_api_key(session)
        async with OpenRouterClient(api_key=api_key) as client:
            result = await client._post("chat/completions", {
                "model": "openai/gpt-4o-mini",
                "messages": [{
                    "role": "system",
                    "content": "You generate short topic labels (2-4 words) from podcast transcript excerpts. Respond with ONLY the label, nothing else."
                }, {
                    "role": "user",
                    "content": f"Generate a short topic label for these transcript excerpts:\n\n{chunk_text}"
                }],
            })
            choices = result.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "Unnamed Topic").strip().strip('"')
    except Exception as e:
        logger.warning("Label generation failed: %s", e)
    return "Unnamed Topic"
