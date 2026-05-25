# Insights Tab & RAG Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an Insights tab (main app + portals) with topic discovery/clustering, cross-series comparison, and RAG question answering over transcribed episodes.

**Architecture:** HDBSCAN clustering runs locally on episode embeddings (daily + manual trigger). pgvector handles topic similarity queries. OpenRouter LLM powers RAG answers. Three new DB tables, four new service/router/template files, integration into existing UI and portal server.

**Tech Stack:** Python scikit-learn (HDBSCAN, TF-IDF), pgvector, OpenRouter chat/completions, Alpine.js, existing Jinja2/FastAPI stack.

---

## File Structure

| File | Responsibility |
|---|---|
| `app/models/topic.py` | TopicCluster and EpisodeTopic SQLAlchemy models |
| `app/services/clustering.py` | HDBSCAN clustering, TF-IDF label extraction, topic assignment |
| `app/services/rag.py` | Embed question → semantic search → LLM answer |
| `app/routers/api_insights.py` | REST API: list topics, topic episodes, comparison data, RAG query |
| `app/templates/insights.html` | Main app Insights tab (3 panels: topics, comparison, RAG) |
| `app/templates/portal_insights.html` | Portal Insights page (2 panels: topics filtered, RAG) |
| `app/main.py` | Register router, add clustering scheduled job |
| `app/routers/ui.py` | Add `/insights` route |
| `app/portal_server.py` | Add portal insights route |
| `app/templates/base.html` | Add "Insights" nav link |
| `app/templates/portal_search.html` | Add "Insights" nav link to portal |
| `pyproject.toml` | Add scikit-learn dependency |

---

### Task 1: Add scikit-learn dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add scikit-learn to dependencies**

Edit `pyproject.toml`, under `dependencies` add:
```toml
"scikit-learn>=1.3",
```

- [ ] **Step 2: Commit**

```bash
git add pyproject.toml
git commit -m "deps: add scikit-learn for clustering"
```

---

### Task 2: Create TopicCluster and EpisodeTopic database models

**Files:**
- Create: `app/models/topic.py`
- Modify: `app/main.py`

- [ ] **Step 1: Create the models file**

Write `app/models/topic.py`:

```python
import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Float, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class TopicCluster(Base):
    __tablename__ = "topic_clusters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(3072), nullable=True)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="auto")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    episode_assignments = relationship("EpisodeTopic", back_populates="topic", cascade="all, delete-orphan")


class EpisodeTopic(Base):
    __tablename__ = "episode_topics"

    topic_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("topic_clusters.id"), primary_key=True)
    episode_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("episodes.id"), primary_key=True)
    score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    topic = relationship("TopicCluster", back_populates="episode_assignments")

    __table_args__ = (UniqueConstraint("topic_id", "episode_id"),)
```

- [ ] **Step 2: Run verify import works**

```bash
python3 -c "from app.models.topic import TopicCluster, EpisodeTopic; print('OK')"
```

- [ ] **Step 3: Commit**

```bash
git add app/models/topic.py
git commit -m "feat: add TopicCluster and EpisodeTopic models"
```

---

### Task 3: Create clustering service

**Files:**
- Create: `app/services/clustering.py`

- [ ] **Step 1: Write the clustering service**

Write `app/services/clustering.py`:

```python
import logging
import numpy as np
from sklearn.cluster import HDBSCAN
from sklearn.feature_extraction.text import TfidfVectorizer

from sqlalchemy import select, delete, func, text

from app.database import async_session
from app.models.episode import Episode
from app.models.topic import TopicCluster, EpisodeTopic
from app.models.transcript import Transcript, TranscriptChunk
from app.services.openrouter import OpenRouterClient, get_api_key
from app.models.setting import Setting

logger = logging.getLogger(__name__)

EMBEDDING_MODEL_KEY = "embedding_model"
DEFAULT_EMBEDDING_MODEL = "openai/text-embedding-3-small"
CLUSTER_MIN_SIZE = 3


async def run_clustering():
    async with async_session() as session:
        rows = await session.execute(
            select(Episode.id, func.avg(TranscriptChunk.embedding).label("avg_emb"))
            .join(Transcript, Transcript.episode_id == Episode.id)
            .join(TranscriptChunk, TranscriptChunk.transcript_id == Transcript.id)
            .where(TranscriptChunk.embedding.is_not(None))
            .group_by(Episode.id)
        )
        episode_data = [(str(r[0]), np.array(r[1], dtype=np.float32)) for r in rows.all()]

        if len(episode_data) < CLUSTER_MIN_SIZE:
            logger.info("Clustering: too few episodes with embeddings (%d), skipping", len(episode_data))
            return

        episode_ids = [e[0] for e in episode_data]
        matrix = np.stack([e[1] for e in episode_data])

        hdbscan = HDBSCAN(min_cluster_size=CLUSTER_MIN_SIZE, metric="euclidean")
        labels = hdbscan.fit_predict(matrix)

        noise_count = int((labels == -1).sum())
        cluster_count = len(set(labels)) - (1 if -1 in labels else 0)
        logger.info("Clustering: %d episodes, %d clusters, %d noise", len(episode_ids), cluster_count, noise_count)

        await session.execute(delete(EpisodeTopic).where(
            EpisodeTopic.topic_id.in_(
                select(TopicCluster.id).where(TopicCluster.source == "auto")
            )
        ))
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
                session.add(EpisodeTopic(topic_id=topic.id, episode_id=uuid.UUID(ep_id), score=1.0))

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
```

- [ ] **Step 2: Add missing import (uuid)**

Edit the file to include `import uuid` at the top.

- [ ] **Step 3: Verify syntax**

```bash
python3 -m py_compile app/services/clustering.py && echo "OK"
```

- [ ] **Step 4: Commit**

```bash
git add app/services/clustering.py
git commit -m "feat: add HDBSCAN clustering service"
```

---

### Task 4: Create RAG service

**Files:**
- Create: `app/services/rag.py`

- [ ] **Step 1: Write the RAG service**

Write `app/services/rag.py`:

```python
import logging

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.episode import Episode
from app.models.podcast import Podcast
from app.models.transcript import TranscriptChunk, Transcript
from app.services.openrouter import OpenRouterClient, get_api_key
from app.models.setting import Setting
from app.services.searcher import EMBEDDING_MODEL_KEY, DEFAULT_EMBEDDING_MODEL, search_semantic

logger = logging.getLogger(__name__)

RAG_SYSTEM_PROMPT = (
    "You are answering questions about podcast transcripts. "
    "Below are relevant transcript excerpts with their sources. "
    "Answer the question using ONLY the excerpts below. "
    "Cite sources at the end as: [PodcastName, Month Year]. "
    "If the excerpts do not contain enough information, say so clearly. "
    "Do not invent facts or hallucinate sources."
)


async def ask_question(
    session: AsyncSession,
    question: str,
    podcast_ids: list[str] | None = None,
) -> dict:
    semantic_results = await search_semantic(
        session, question,
        podcast_ids=podcast_ids,
        limit=20,
    )

    if not semantic_results:
        return {
            "answer": "No relevant transcript excerpts were found for your question.",
            "sources": [],
        }

    sources = []
    chunks_text = []
    for i, r in enumerate(semantic_results):
        label = f"{r['podcast_title']}, {r.get('published_at', '')[:10]}"
        chunks_text.append(f"Excerpt {i + 1} [{label}]:\n{r['snippet']}")
        sources.append({
            "episode_id": r["episode_id"],
            "episode_title": r["episode_title"],
            "podcast_title": r["podcast_title"],
            "published_at": r.get("published_at"),
        })

    chunk_block = "\n\n".join(chunks_text)
    user_message = f"---\n{chunk_block}\n---\nQuestion: {question}"

    model_setting = await session.get(Setting, "summarization_model")
    model = model_setting.value if model_setting else "openai/gpt-4o-mini"
    api_key = await get_api_key(session)

    async with OpenRouterClient(api_key=api_key) as client:
        result = await client._post("chat/completions", {
            "model": model,
            "messages": [
                {"role": "system", "content": RAG_SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        })

    choices = result.get("choices", [])
    answer = choices[0].get("message", {}).get("content", "") if choices else "Unable to generate answer."

    return {"answer": answer, "sources": sources}
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -m py_compile app/services/rag.py && echo "OK"
```

- [ ] **Step 3: Commit**

```bash
git add app/services/rag.py
git commit -m "feat: add RAG question-answering service"
```

---

### Task 5: Create Insights API endpoints

**Files:**
- Create: `app/routers/api_insights.py`

- [ ] **Step 1: Write the API router**

Write `app/routers/api_insights.py`:

```python
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.episode import Episode
from app.models.podcast import Podcast
from app.models.topic import TopicCluster, EpisodeTopic
from app.services.clustering import run_clustering
from app.services.rag import ask_question

router = APIRouter(prefix="/api/insights", tags=["insights"])


@router.get("/topics")
async def list_topics(
    podcast_ids: str | None = Query(None, description="Comma-separated podcast IDs"),
    db: AsyncSession = Depends(get_db),
):
    query = select(
        TopicCluster.id, TopicCluster.label, TopicCluster.description,
        TopicCluster.source, TopicCluster.created_at,
        func.count(EpisodeTopic.episode_id).label("episode_count"),
    ).outerjoin(EpisodeTopic, EpisodeTopic.topic_id == TopicCluster.id)

    if podcast_ids:
        pid_list = podcast_ids.split(",")
        query = query.outerjoin(Episode, Episode.id == EpisodeTopic.episode_id)
        query = query.where(
            (EpisodeTopic.episode_id.is_(None)) | (Episode.podcast_id.in_(pid_list))
        ).distinct()

    query = query.group_by(TopicCluster.id).order_by(func.count(EpisodeTopic.episode_id).desc())
    result = await db.execute(query)
    rows = result.all()

    return [
        {
            "id": str(r.id),
            "label": r.label,
            "description": r.description,
            "source": r.source,
            "episode_count": r.episode_count,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


@router.get("/topics/{topic_id}/episodes")
async def topic_episodes(
    topic_id: UUID,
    podcast_ids: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(Episode, EpisodeTopic.score, Podcast.title.label("podcast_title"))
        .join(EpisodeTopic, EpisodeTopic.episode_id == Episode.id)
        .join(Podcast, Podcast.id == Episode.podcast_id)
        .where(EpisodeTopic.topic_id == topic_id)
    )
    if podcast_ids:
        query = query.where(Episode.podcast_id.in_(podcast_ids.split(",")))
    query = query.order_by(EpisodeTopic.score.desc()).limit(100)

    result = await db.execute(query)
    rows = result.all()

    return [
        {
            "id": str(r.Episode.id),
            "title": r.Episode.title,
            "podcast_title": r.podcast_title,
            "published_at": r.Episode.published_at.isoformat() if r.Episode.published_at else None,
            "score": round(r.score, 3),
        }
        for r in rows
    ]


@router.get("/comparison")
async def cross_series_comparison(
    podcast_ids: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    topic_query = select(TopicCluster.id, TopicCluster.label).order_by(TopicCluster.label)
    topics = (await db.execute(topic_query)).all()

    podcast_query = select(Podcast.id, Podcast.title).order_by(Podcast.title)
    if podcast_ids:
        podcast_query = podcast_query.where(Podcast.id.in_(podcast_ids.split(",")))
    podcasts = (await db.execute(podcast_query)).all()

    comparison = []
    for topic in topics:
        row = {"topic_id": str(topic.id), "topic": topic.label, "podcasts": {}}
        for p in podcasts:
            total = (
                await db.execute(
                    select(func.count(Episode.id)).where(Episode.podcast_id == p.id)
                )
            ).scalar_one() or 1
            matched = (
                await db.execute(
                    select(func.count(EpisodeTopic.episode_id))
                    .join(Episode, Episode.id == EpisodeTopic.episode_id)
                    .where(
                        EpisodeTopic.topic_id == topic.id,
                        Episode.podcast_id == p.id,
                    )
                )
            ).scalar_one() or 0
            row["podcasts"][str(p.id)] = {
                "title": p.title,
                "matched": matched,
                "total": total,
                "pct": round(matched / total * 100, 1),
            }
        comparison.append(row)

    return {
        "topics": comparison,
        "podcasts": [{"id": str(p.id), "title": p.title} for p in podcasts],
    }


@router.post("/rag")
async def rag_query(
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    question = body.get("question", "").strip()
    podcast_ids = body.get("podcast_ids")  # optional list
    if not question:
        return {"error": "question is required"}

    result = await ask_question(session=db, question=question, podcast_ids=podcast_ids)
    return result


@router.post("/clusters/refresh")
async def refresh_clusters():
    await run_clustering()
    return {"status": "clustering started"}
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -m py_compile app/routers/api_insights.py && echo "OK"
```

- [ ] **Step 3: Commit**

```bash
git add app/routers/api_insights.py
git commit -m "feat: add insights API endpoints (topics, comparison, RAG, clustering)"
```

---

### Task 6: Register Insights router and clustering job in main.py

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: Add router import and registration**

In `app/main.py`, after the existing router imports (around line 80), add:
```python
from app.routers import api_podcasts, api_episodes, api_queue, api_search, api_settings, ui, api_portals, api_abs, api_insights
```

And after the existing `app.include_router` calls, add:
```python
app.include_router(api_insights.router)
```

- [ ] **Step 2: Add clustering import**

At the top of `app/main.py`, add the import:
```python
from app.services.clustering import run_clustering
```

- [ ] **Step 3: Add clustering scheduled job**

After the existing `scheduler.add_job` calls, add:
```python
scheduler.add_job(
    run_clustering,
    trigger="cron",
    hour=3,
    minute=0,
    id="daily_clustering",
    replace_existing=True,
)
```

- [ ] **Step 4: Verify syntax**

```bash
python3 -m py_compile app/main.py && echo "OK"
```

- [ ] **Step 5: Commit**

```bash
git add app/main.py
git commit -m "feat: register insights router and daily clustering job"
```

---

### Task 7: Add Insights navigation link to base template

**Files:**
- Modify: `app/templates/base.html`

- [ ] **Step 1: Add Insights nav link**

Find the nav links section in `app/templates/base.html`. Look for links like "Dashboard", "Queue", "Admin". Add an "Insights" link:

```html
<a href="/insights" class="nav-link">Insights</a>
```

Place it between existing links (e.g., after Queue, before Admin).

- [ ] **Step 2: Commit**

```bash
git add app/templates/base.html
git commit -m "feat: add Insights nav link to base template"
```

---

### Task 8: Add Insights route to UI router

**Files:**
- Modify: `app/routers/ui.py`

- [ ] **Step 1: Add /insights route**

In `app/routers/ui.py`, add a new route after the existing ones:

```python
@router.get("/insights", response_class=HTMLResponse)
async def insights_page(request: Request):
    return templates.TemplateResponse(request, "insights.html")
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -m py_compile app/routers/ui.py && echo "OK"
```

- [ ] **Step 3: Commit**

```bash
git add app/routers/ui.py
git commit -m "feat: add /insights route to UI router"
```

---

### Task 9: Create Insights tab template (main app)

**Files:**
- Create: `app/templates/insights.html`

- [ ] **Step 1: Write the Insights template**

Write `app/templates/insights.html`:

```html
{% extends "base.html" %}
{% block content %}
<div x-data="insightsView()" x-init="init()">
  <div class="flex items-center justify-between mb-6">
    <h1 class="page-title">Insights</h1>
    <button @click="refreshClusters()" class="btn btn-ghost btn-sm" x-text="clustering ? 'Clustering...' : 'Refresh Topics'"></button>
  </div>

  <div class="flex flex-col gap-8">

    <!-- RAG: Ask a Question -->
    <div class="card" style="padding:20px;">
      <h2 class="section-title mb-3">Ask a Question</h2>
      <div class="flex flex-col gap-3">
        <div class="flex gap-3">
          <input type="text" x-model="ragQuestion" @keyup.enter="askQuestion()"
                 placeholder="e.g. How many episodes discuss the German economy?"
                 class="input flex-1" style="border-radius:6px;">
          <button @click="askQuestion()" :disabled="ragLoading" class="btn btn-primary btn-sm"
                  x-text="ragLoading ? 'Asking...' : 'Ask'"></button>
        </div>
        <div x-show="ragAnswer" class="p-4 rounded-lg" style="background:var(--bg-elevated);border:1px solid var(--border-subtle);">
          <div class="text-sm leading-relaxed whitespace-pre-wrap" x-text="ragAnswer"></div>
          <template x-if="ragSources.length > 0">
            <div class="mt-3 pt-3 border-t" style="border-color:var(--border-subtle);">
              <p class="text-xs font-medium text-secondary mb-2">Sources:</p>
              <template x-for="s in ragSources" :key="s.episode_id">
                <a :href="'/episodes/' + s.episode_id" class="block text-xs text-accent hover:underline mt-1"
                   x-text="s.podcast_title + ' — ' + s.episode_title"></a>
              </template>
            </div>
          </template>
        </div>
      </div>
    </div>

    <!-- Topic Browser -->
    <div class="card" style="padding:20px;">
      <h2 class="section-title mb-3">Topics</h2>

      <div class="flex items-center gap-3 mb-4">
        <input type="text" x-model="topicFilter" placeholder="Filter topics..." class="input input-pill" style="flex:1;">
        <button @click="showCreateTopic = !showCreateTopic" class="btn btn-primary btn-sm">+ Create Topic</button>
      </div>

      <div x-show="showCreateTopic" class="flex flex-col gap-3 mb-4" style="padding:16px;background:var(--bg-elevated);border-radius:8px;">
        <input x-model="newTopicLabel" placeholder="Topic label (e.g. Climate Policy)" class="input" style="border-radius:6px;">
        <div class="flex gap-2">
          <button @click="createTopic()" class="btn btn-primary btn-sm">Create</button>
          <button @click="showCreateTopic = false" class="btn btn-ghost btn-sm">Cancel</button>
        </div>
      </div>

      <div x-show="loading" class="flex items-center gap-3 text-sm text-secondary" style="padding:16px 0;">
        <div class="spinner"></div> Loading topics...
      </div>

      <div class="flex flex-col gap-2">
        <template x-for="t in filteredTopics" :key="t.id">
          <div class="flex items-center justify-between" style="padding:12px 16px;background:var(--bg-surface);border-radius:6px;border:1px solid var(--border-subtle);">
            <div class="flex items-center gap-3">
              <span class="badge" :class="t.source === 'auto' ? 'badge-blue' : 'badge-green'" style="font-size:0.688rem;" x-text="t.source === 'auto' ? 'auto' : 'custom'"></span>
              <span class="text-sm font-medium" x-text="t.label"></span>
              <span class="text-2xs text-tertiary" x-text="t.episode_count + ' episodes'"></span>
            </div>
            <div class="flex items-center gap-2">
              <button @click="viewTopicEpisodes(t)" class="btn btn-ghost btn-sm text-accent">View</button>
              <button @click="deleteTopic(t)" x-show="t.source === 'manual'" class="btn btn-ghost btn-sm text-red">Delete</button>
            </div>
          </div>
        </template>
        <p x-show="!loading && filteredTopics.length === 0" class="text-sm text-tertiary" style="padding:16px;">
          No topics yet. Create one or wait for automatic clustering.
        </p>
      </div>
    </div>

    <!-- Cross-Series Comparison -->
    <div class="card" style="padding:20px;">
      <h2 class="section-title mb-3">Cross-Series Comparison</h2>
      <div x-show="comparisonLoading" class="flex items-center gap-3 text-sm text-secondary" style="padding:16px 0;">
        <div class="spinner"></div> Loading...
      </div>
      <div x-show="!comparisonLoading" class="overflow-x-auto">
        <table class="w-full text-xs">
          <thead>
            <tr>
              <th class="text-left p-2 text-secondary font-medium">Topic</th>
              <template x-for="p in comparisonPodcasts" :key="p.id">
                <th class="text-left p-2 text-secondary font-medium" x-text="p.title"></th>
              </template>
            </tr>
          </thead>
          <tbody>
            <template x-for="t in comparisonTopics" :key="t.topic_id">
              <tr>
                <td class="p-2 font-medium" x-text="t.topic"></td>
                <template x-for="pid in comparisonPodcastIds" :key="pid">
                  <td class="p-2" x-text="(t.podcasts[pid]?.pct || 0) + '%' "></td>
                </template>
              </tr>
            </template>
          </tbody>
        </table>
        <p x-show="comparisonTopics.length === 0" class="text-sm text-tertiary" style="padding:16px;">
          No data yet.
        </p>
      </div>
    </div>

    <!-- Episode Modal -->
    <div x-show="episodeModal" x-cloak class="modal-overlay">
      <div class="modal" style="max-width:600px;">
        <h2 class="modal-title" x-text="'Episodes: ' + episodeModalTopic.label"></h2>
        <div class="flex flex-col gap-1 mt-3" style="max-height:400px;overflow-y:auto;">
          <template x-for="ep in episodeModalList" :key="ep.id">
            <a :href="'/episodes/' + ep.id" class="flex items-center gap-3" style="padding:10px 12px;border-radius:6px;"
               @mouseenter="$el.style.background='var(--bg-elevated)'" @mouseleave="$el.style.background='transparent'">
              <span class="text-sm truncate flex-1">
                <span class="font-medium" x-text="ep.title"></span>
                <span class="text-tertiary text-2xs ml-2" x-text="ep.podcast_title"></span>
              </span>
              <span class="text-2xs text-tertiary" x-text="new Date(ep.published_at).toLocaleDateString('da-DK', {day:'2-digit', month:'short'})"></span>
            </a>
          </template>
        </div>
        <div class="flex justify-end mt-4">
          <button @click="episodeModal = false" class="btn btn-ghost btn-sm">Close</button>
        </div>
      </div>
    </div>

  </div>
</div>

<style>
.table { width: 100%; border-collapse: collapse; }
.table th { border-bottom: 1px solid var(--border-subtle); }
.table td { border-bottom: 1px solid var(--border-subtle); }
.modal { background: var(--bg-surface); border: 1px solid var(--border-subtle); border-radius: 12px; padding: 24px; width: 100%; max-height: 90vh; overflow-y: auto; }
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: flex; align-items: center; justify-content: center; z-index: 100; padding: 20px; }
.modal-title { font-size: 1.1rem; font-weight: 700; margin-bottom: 4px; }
</style>

<script>
function insightsView() {
  return {
    topics: [], topicFilter: '', showCreateTopic: false, newTopicLabel: '', loading: true, clustering: false,
    ragQuestion: '', ragAnswer: '', ragSources: [], ragLoading: false,
    comparisonTopics: [], comparisonPodcasts: [], comparisonPodcastIds: [], comparisonLoading: false,
    episodeModal: false, episodeModalList: [], episodeModalTopic: null,

    get filteredTopics() {
      if (!this.topicFilter) return this.topics;
      const q = this.topicFilter.toLowerCase();
      return this.topics.filter(t => t.label.toLowerCase().includes(q));
    },

    async init() {
      await Promise.all([this.loadTopics(), this.loadComparison()]);
      this.loading = false;
    },

    async loadTopics() {
      try {
        const r = await fetch('/api/insights/topics');
        this.topics = await r.json();
      } catch(e) { console.error(e); }
    },

    async createTopic() {
      if (!this.newTopicLabel.trim()) return;
      await fetch('/api/insights/topics/create', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({label: this.newTopicLabel.trim()}),
      });
      this.showCreateTopic = false;
      this.newTopicLabel = '';
      await this.loadTopics();
    },

    async deleteTopic(t) {
      await fetch('/api/insights/topics/' + t.id, { method: 'DELETE' });
      await this.loadTopics();
    },

    async viewTopicEpisodes(t) {
      const r = await fetch('/api/insights/topics/' + t.id + '/episodes');
      this.episodeModalList = await r.json();
      this.episodeModalTopic = t;
      this.episodeModal = true;
    },

    async refreshClusters() {
      this.clustering = true;
      await fetch('/api/insights/clusters/refresh', { method: 'POST' });
      setTimeout(async () => { await this.loadTopics(); this.clustering = false; }, 5000);
    },

    async askQuestion() {
      if (!this.ragQuestion.trim()) return;
      this.ragLoading = true;
      this.ragAnswer = '';
      this.ragSources = [];
      try {
        const r = await fetch('/api/insights/rag', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({question: this.ragQuestion}),
        });
        const data = await r.json();
        this.ragAnswer = data.answer || 'No answer.';
        this.ragSources = data.sources || [];
      } catch(e) { this.ragAnswer = 'Error: ' + e.message; }
      this.ragLoading = false;
    },

    async loadComparison() {
      this.comparisonLoading = true;
      try {
        const r = await fetch('/api/insights/comparison');
        const data = await r.json();
        this.comparisonTopics = data.topics || [];
        this.comparisonPodcasts = data.podcasts || [];
        this.comparisonPodcastIds = this.comparisonPodcasts.map(p => p.id);
      } catch(e) { console.error(e); }
      this.comparisonLoading = false;
    },
  };
}
</script>
{% endblock %}
```

- [ ] **Step 2: Commit**

```bash
git add app/templates/insights.html
git commit -m "feat: add insights tab template"
```

---

### Task 10: Create Portal Insights template

**Files:**
- Create: `app/templates/portal_insights.html`

- [ ] **Step 1: Write the portal insights template**

Write `app/templates/portal_insights.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{{ portal.title }} — Insights</title>
  <script src="https://unpkg.com/alpinejs@3.14.8" defer></script>
  <style>
    :root {
      --bg-body: #0f172a;
      --bg-card: rgba(0,0,0,0.42);
      --bg-elevated: rgba(0,0,0,0.30);
      --bg-input: rgba(0,0,0,0.48);
      --border: rgba(255,255,255,0.10);
      --text: #f1f5f9;
      --text-secondary: #94a3b8;
      --text-dim: #64748b;
      --accent: #10b981;
      --radius: 12px;
    }
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
      background: linear-gradient(135deg, #0f172a 0%, #1e3a5f 50%, #0f172a 100%);
      color: var(--text); min-height: 100vh; line-height: 1.5;
      -webkit-font-smoothing: antialiased;
    }
    body.has-bg { background: none; }
    .bg-image { position: fixed; inset: 0; z-index: -1; background-position: center; background-size: cover; }
    .overlay { min-height: 100vh; }
    .overlay.has-bg { background: linear-gradient(rgba(0,0,0,0.60), rgba(0,0,0,0.85)); }
    .container { max-width: 860px; margin: 0 auto; padding: 40px 20px; }
    .back-link { display: inline-flex; align-items: center; gap: 4px; font-size: 0.875rem; color: var(--accent); text-decoration: none; font-weight: 500; margin-bottom: 24px; }
    .back-link:hover { color: #34d399; }
    .back-link svg { width: 14px; height: 14px; }
    .page-title { font-size: 2rem; font-weight: 700; color: #fff; margin-bottom: 4px; letter-spacing: -0.01em; }
    .section-title { font-size: 0.85rem; font-weight: 700; color: var(--text-secondary); margin-bottom: 12px; text-transform: uppercase; letter-spacing: 0.06em; }
    .card { background: var(--bg-card); border: 1px solid var(--border); border-radius: var(--radius); -webkit-backdrop-filter: blur(12px); backdrop-filter: blur(12px); }
    .input { width: 100%; padding: 12px 16px; font-size: 0.9rem; color: var(--text); background: var(--bg-input); border: 1px solid var(--border); border-radius: var(--radius); outline: none; font-family: inherit; transition: border-color 0.2s; }
    .input:focus { border-color: var(--accent); background: rgba(0,0,0,0.60); }
    .input::placeholder { color: var(--text-dim); }
    .btn { display: inline-flex; align-items: center; justify-content: center; padding: 12px 24px; font-size: 0.875rem; font-weight: 600; color: #fff; background: var(--accent); border: none; border-radius: var(--radius); cursor: pointer; font-family: inherit; transition: background 0.2s; }
    .btn:hover { background: #059669; }
    .btn:disabled { opacity: 0.5; cursor: default; }
    .btn-sm { padding: 8px 16px; font-size: 0.8rem; }
    .badge { display: inline-block; font-size: 0.688rem; font-weight: 600; padding: 2px 8px; border-radius: 4px; }
    .badge-blue { background: #1d4ed8; color: #bfdbfe; }
    .badge-green { background: #047857; color: #a7f3d0; }
    .spinner { display: inline-block; width: 20px; height: 20px; border: 2px solid rgba(255,255,255,0.2); border-top-color: var(--accent); border-radius: 50%; animation: spin 0.6s linear infinite; margin-right: 8px; vertical-align: middle; }
    @keyframes spin { to { transform: rotate(360deg); } }
    [x-cloak] { display: none !important; }
  </style>
</head>
<body :class="hasBg ? 'has-bg' : ''" x-data="portalInsights()" x-init="loadTopics()" x-cloak>

  <div x-show="hasBg" class="bg-image" :style="'background-image: url(' + bgImage + ')'"></div>

  <div class="overlay" :class="hasBg ? 'has-bg' : ''">
    <div class="container">
      <a href="/" class="back-link">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <polyline points="15 18 9 12 15 6"/>
        </svg>
        Back to search
      </a>

      <h1 class="page-title">Insights</h1>

      <!-- Ask a Question -->
      <div class="card" style="padding:20px; margin-top:24px;">
        <h2 class="section-title">Ask a Question</h2>
        <div class="flex flex-col gap-3">
          <div style="display:flex; gap:12px;">
            <input type="text" x-model="ragQuestion" @keyup.enter="askQuestion()"
                   placeholder="e.g. How many episodes discuss climate change?"
                   class="input" style="flex:1;">
            <button @click="askQuestion()" :disabled="ragLoading" class="btn btn-sm"
                    x-text="ragLoading ? '...' : 'Ask'"></button>
          </div>
          <div x-show="ragAnswer" class="p-4 rounded-lg" style="background:rgba(0,0,0,0.3);border:1px solid var(--border);">
            <div class="text-sm leading-relaxed whitespace-pre-wrap" x-text="ragAnswer"></div>
            <template x-if="ragSources.length > 0">
              <div class="mt-3 pt-3 border-t" style="border-color:var(--border);">
                <p class="text-xs font-medium" style="color:var(--text-dim); margin-bottom:6px;">Sources:</p>
                <template x-for="s in ragSources" :key="s.episode_id">
                  <a :href="'/episodes/' + s.episode_id" class="block text-xs" style="color:var(--accent); margin-top:4px;"
                     x-text="s.podcast_title + ' — ' + s.episode_title"></a>
                </template>
              </div>
            </template>
          </div>
        </div>
      </div>

      <!-- Topics -->
      <div class="card" style="padding:20px; margin-top:24px;">
        <h2 class="section-title">Topics</h2>

        <div x-show="loading" class="flex items-center gap-3" style="color:var(--text-dim); padding:16px 0;">
          <div class="spinner"></div> Loading...
        </div>

        <div style="display:flex; flex-direction:column; gap:8px;">
          <template x-for="t in topics" :key="t.id">
            <div style="display:flex; align-items:center; justify-content:space-between; padding:12px 16px; background:rgba(0,0,0,0.2); border-radius:8px; border:1px solid var(--border);">
              <div style="display:flex; align-items:center; gap:12px;">
                <span class="badge" :class="t.source === 'auto' ? 'badge-blue' : 'badge-green'" x-text="t.source === 'auto' ? 'auto' : 'custom'"></span>
                <span style="font-size:0.9rem; font-weight:500;" x-text="t.label"></span>
                <span style="font-size:0.688rem; color:var(--text-dim);" x-text="t.episode_count + ' episodes'"></span>
              </div>
              <button @click="viewEpisodes(t)" class="btn btn-sm" style="background:transparent; border:1px solid var(--border); color:var(--text);">View</button>
            </div>
          </template>
          <p x-show="!loading && topics.length === 0" style="color:var(--text-dim); padding:16px; text-align:center;">
            No topics yet.
          </p>
        </div>
      </div>

      <!-- Episode modal -->
      <div x-show="modal" x-cloak style="position:fixed; inset:0; background:rgba(0,0,0,0.6); display:flex; align-items:center; justify-content:center; z-index:100; padding:20px;">
        <div style="background:var(--bg-card); border:1px solid var(--border); border-radius:var(--radius); padding:24px; width:100%; max-width:600px; max-height:80vh; overflow-y:auto;">
          <h2 style="font-size:1.1rem; font-weight:700; margin-bottom:16px;" x-text="modalTopic?.label"></h2>
          <div style="display:flex; flex-direction:column; gap:4px;">
            <template x-for="ep in modalEpisodes" :key="ep.id">
              <a :href="'/episodes/' + ep.id" style="display:flex; gap:12px; padding:10px 12px; border-radius:6px; text-decoration:none; color:inherit;"
                 @mouseenter="$el.style.background='var(--bg-input)'" @mouseleave="$el.style.background='transparent'">
                <span style="font-size:0.9rem; flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                  <span style="font-weight:500;" x-text="ep.title"></span>
                  <span style="font-size:0.688rem; color:var(--text-dim); margin-left:8px;" x-text="ep.podcast_title"></span>
                </span>
              </a>
            </template>
          </div>
          <div style="display:flex; justify-content:flex-end; margin-top:16px;">
            <button @click="modal = false" class="btn btn-sm" style="background:transparent; border:1px solid var(--border); color:var(--text);">Close</button>
          </div>
        </div>
      </div>

    </div>
  </div>

<script>
function portalInsights() {
  return {
    portalId: '{{ portal.id }}',
    podcastIds: {{ portal.podcast_ids|tojson }},
    bgImage: '{{ portal.background_image or portal.secondary_image or "" }}',
    hasBg: !!({{ portal.background_image|tojson }} || {{ portal.secondary_image|tojson }}),
    topics: [], loading: true,
    ragQuestion: '', ragAnswer: '', ragSources: [], ragLoading: false,
    modal: false, modalEpisodes: [], modalTopic: null,

    async loadTopics() {
      try {
        const r = await fetch('/api/insights/topics?podcast_ids=' + this.podcastIds.join(','));
        this.topics = await r.json();
      } catch(e) { console.error(e); }
      this.loading = false;
    },

    async viewEpisodes(t) {
      const r = await fetch('/api/insights/topics/' + t.id + '/episodes?podcast_ids=' + this.podcastIds.join(','));
      this.modalEpisodes = await r.json();
      this.modalTopic = t;
      this.modal = true;
    },

    async askQuestion() {
      if (!this.ragQuestion.trim()) return;
      this.ragLoading = true;
      this.ragAnswer = '';
      this.ragSources = [];
      try {
        const r = await fetch('/api/insights/rag', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({question: this.ragQuestion, podcast_ids: this.podcastIds}),
        });
        const data = await r.json();
        this.ragAnswer = data.answer || 'No answer.';
        this.ragSources = data.sources || [];
      } catch(e) { this.ragAnswer = 'Error: ' + e.message; }
      this.ragLoading = false;
    },
  };
}
</script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add app/templates/portal_insights.html
git commit -m "feat: add portal insights template"
```

---

### Task 11: Add portal insights route to portal_server.py

**Files:**
- Modify: `app/portal_server.py`

- [ ] **Step 1: Add insight route**

In `app/portal_server.py`, after the `/episodes/{episode_id}` route, add a new route:

```python
@portal_router.get("/insights", response_class=HTMLResponse)
async def portal_insights(request: Request):
    from app.database import async_session
    from app.models.portal import Portal
    async with async_session() as session:
        portal = await session.get(Portal, portal_id)
        if not portal:
            return HTMLResponse("Portal not found", status_code=404)
    return templates.TemplateResponse(
        request, "portal_insights.html", context={"portal": portal},
    )
```

Also register the insights API router on the portal app. After `app.include_router(api_episodes.router)`, add:

```python
from app.routers import api_insights
app.include_router(api_insights.router)
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -m py_compile app/portal_server.py && echo "OK"
```

- [ ] **Step 3: Commit**

```bash
git add app/portal_server.py
git commit -m "feat: add portal insights route"
```

---

### Task 12: Add Insights link to portal search page

**Files:**
- Modify: `app/templates/portal_search.html`

- [ ] **Step 1: Add nav link**

Find the header section of `app/templates/portal_search.html` (around the `<div class="header">` block). Add an "Insights" link between the header and the search form:

```html
<div style="text-align:center; margin-bottom:32px;">
  <a href="/insights" style="display:inline-flex; align-items:center; gap:6px; font-size:0.875rem; color:var(--accent); text-decoration:none; font-weight:500; padding:8px 16px; border:1px solid var(--accent); border-radius:8px; transition:0.2s;"
     onmouseenter="this.style.background='rgba(16,185,129,0.1)'" onmouseleave="this.style.background='transparent'">
    Insights
  </a>
</div>
```

- [ ] **Step 2: Commit**

```bash
git add app/templates/portal_search.html
git commit -m "feat: add Insights link to portal search page"
```

---

### Task 13: Add manual topic creation endpoint + delete

**Files:**
- Modify: `app/routers/api_insights.py`

- [ ] **Step 1: Add create and delete endpoints**

Add to `app/routers/api_insights.py`:

```python
import numpy as np

from app.services.openrouter import OpenRouterClient, get_api_key
from app.models.setting import Setting

EMBEDDING_DIM = 3072


@router.post("/topics/create")
async def create_topic(body: dict, db: AsyncSession = Depends(get_db)):
    label = body.get("label", "").strip()
    if not label:
        return {"error": "label is required"}

    model_setting = await db.get(Setting, "embedding_model")
    model = model_setting.value if model_setting else "openai/text-embedding-3-small"
    api_key = await get_api_key(db)

    async with OpenRouterClient(api_key=api_key) as client:
        embedding = await client.embed(model, label)

    topic = TopicCluster(label=label, embedding=embedding, source="manual")
    db.add(topic)
    await db.flush()

    embedding_str = "'[" + ",".join(str(v) for v in embedding) + "]'::vector"
    rows = await db.execute(
        select(Episode.id, func.avg(TranscriptChunk.embedding).label("avg_emb"))
        .join(Transcript, Transcript.episode_id == Episode.id)
        .join(TranscriptChunk, TranscriptChunk.transcript_id == Transcript.id)
        .where(TranscriptChunk.embedding.is_not(None))
        .group_by(Episode.id)
    )
    for r in rows.all():
        dist = await db.execute(
            select(text(f"1.0 - ({embedding_str} <=> :avg_vec)::float"))
            .params(avg_vec=r.avg_emb)
        )
        score = dist.scalar_one()
        if score and score > 0.65:
            db.add(EpisodeTopic(topic_id=topic.id, episode_id=r.id, score=round(score, 3)))

    await db.commit()
    return {"id": str(topic.id), "label": label, "source": "manual"}


@router.delete("/topics/{topic_id}")
async def delete_topic(topic_id: UUID, db: AsyncSession = Depends(get_db)):
    topic = await db.get(TopicCluster, topic_id)
    if not topic:
        return {"error": "not found"}
    if topic.source != "manual":
        return {"error": "cannot delete auto-generated topics"}
    await db.delete(topic)
    await db.commit()
    return {"status": "deleted"}
```

- [ ] **Step 2: Verify syntax**

```bash
python3 -m py_compile app/routers/api_insights.py && echo "OK"
```

- [ ] **Step 3: Commit**

```bash
git add app/routers/api_insights.py
git commit -m "feat: add manual topic creation and deletion endpoints"
```

---

### Task 14: Add migration for new tables and clean up clustering imports

**Files:**
- Modify: `app/main.py`
- Create: (none, tables are auto-created via `Base.metadata.create_all` in lifespan)

- [ ] **Step 1: Ensure models are imported before table creation**

In `app/main.py`, add the topic model import near the other model imports:

```python
from app.models.topic import TopicCluster, EpisodeTopic
```

This ensures `Base.metadata` knows about the new tables before `create_all` runs.

- [ ] **Step 2: Add missing imports to clustering.py**

Edit `app/services/clustering.py` to add `import uuid` at the top if not already present:

```python
import uuid
```

- [ ] **Step 3: Verify everything compiles**

```bash
python3 -m py_compile app/main.py && python3 -m py_compile app/services/clustering.py && echo "All OK"
```

- [ ] **Step 4: Commit**

```bash
git add app/main.py app/services/clustering.py
git commit -m "fix: register topic models for auto-migration, add missing imports"
```

---

### Task 15: Final integration test

**Files:**
- None (verification only)

- [ ] **Step 1: Build and start the container**

```bash
docker build -t podcast-transcription-search:local . && IMAGE=podcast-transcription-search:local docker compose up -d web
```

- [ ] **Step 2: Check logs for clustering job registration**

```bash
docker compose logs web | grep -i "cluster\|insight\|topic"
```

Expected: No errors. Should see the new insights router registered.

- [ ] **Step 3: Verify /insights page loads**

```bash
curl -s http://localhost:8002/insights | head -20
```

Expected: HTML content with "Insights" title.

- [ ] **Step 4: Verify API endpoints respond**

```bash
curl -s http://localhost:8002/api/insights/topics
curl -s http://localhost:8002/api/insights/comparison
```

Expected: JSON arrays (possibly empty if no data).

- [ ] **Step 5: Commit any final tweaks and push**

```bash
git push origin master
```
