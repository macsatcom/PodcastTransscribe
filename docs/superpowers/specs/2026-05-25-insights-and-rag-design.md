# Insights Tab & RAG — Design Spec

## Overview

Add an "Insights" tab to the main dashboard and public portals that provides topic analytics and AI-powered question answering over transcribed podcast episodes. All compute runs locally on existing infrastructure (pgvector + CPU), with LLM queries routed through the existing OpenRouter API key.

---

## Architecture

Three new capabilities, no new infrastructure:

| Layer | Technology |
|---|---|
| Clustering | Python HDBSCAN on episode embeddings, runs via scheduled APScheduler job |
| Topic similarity | pgvector `<=>` on existing `transcript_chunks.embedding` |
| RAG answers | Retrieve chunks via pgvector → OpenRouter `chat/completions` |

All queries hit the existing pgvector database. Clustering runs on CPU (a few thousand episodes takes seconds). OpenRouter costs are under $0.02 per RAG question.

---

## New Database Tables

```
topic_clusters
  id          UUID PK
  label       TEXT           (human-readable name, e.g. "German Economy")
  description TEXT           (optional longer description)
  embedding   VECTOR(3072)   (centroid of cluster, or the search-term embedding for manual topics)
  source      TEXT           ("auto" = discovered by clustering, "manual" = user-defined)
  portal_id   UUID FK nullable (NULL = global/main app, set = specific portal)
  created_at  TIMESTAMPTZ

episode_topics
  topic_id     UUID FK -> topic_clusters.id
  episode_id   UUID FK -> episodes.id
  score        FLOAT          (relevance score, 0.0-1.0)
  PRIMARY KEY (topic_id, episode_id)
```

---

## Panel 1: Topic Browser

### Main App

Shows both auto-discovered and manual topics as a scrollable list/cloud. Each topic card shows:
- Topic label and episode count
- Click to expand: list of matching episodes, timeline chart (episodes by month), top podcast series

UI elements:
- **Create topic** button: text input + optional keyword for pre-defined topics. System embeds the label, finds matching episodes via cosine distance < 0.35 on the average episode embedding.
- **Rename/delete** buttons on each topic (admin only).
- **Refresh clusters** button: re-runs the clustering job on demand.

### Public Portal

Read-only. Shows only topics matching the portal's podcast collection (global clustering, filtered at query time by portal's `podcast_ids`). No create/rename/delete. Same browsing UX.

---

## Panel 2: Cross-Series Comparison (Main App Only)

Side-by-side topic coverage per podcast series. A table where:
- Rows = topic clusters (auto + manual)
- Columns = podcast series
- Cells = percentage of episodes in that podcast that match the topic

Example:
```
Topic              | Vildt Naturligt | Radioavisen | Slotsholmen
Wildlife            | 42%            | 1%          | 0%
Economy             | 2%             | 18%         | 25%
```

Clickable cells drill down into the matching episode list.

---

## Panel 3: Ask a Question (RAG)

### Flow

1. User types a question, e.g. "How many episodes discuss the German economy?"
2. System embeds the question via the configured embedding model (same as transcription indexing).
3. pgvector semantic search retrieves top-20 most similar transcript chunks within relevance threshold (distance < 0.5).
4. Chunks + question + system prompt sent to OpenRouter `chat/completions` using the configured summarization model.
5. LLM responds with: text answer + episode citations (title, date, link).

### System Prompt Template

```
You are answering questions about podcast transcripts.
Below are relevant transcript excerpts with their sources.
Answer the question using ONLY the excerpts below.
Cite sources at the end as: [PodcastName, Month Year]
If the excerpts do not contain enough information, say so clearly.
Do not invent facts or hallucinate sources.
---
{chunks_with_sources}
---
Question: {user_question}
```

### UI

- Single text input at the top of the Insights tab.
- Answer panel below with formatted response and clickable episode links.
- Loading state during processing.
- Conversation history (scrollable, last N Q&A pairs within the session).

### On Portals

Same flow but episode retrieval is pre-filtered to the portal's `podcast_ids`. The question input and answer panel are shown on the portal Insights page.

---

## Clustering Engine

### How It Works

1. A scheduled APScheduler job runs after new transcriptions (or daily at 3am).
2. Fetches the average embedding per episode (mean of its `transcript_chunks.embedding` values) via pgvector.
3. Runs HDBSCAN on the episode embedding matrix. HDBSCAN is chosen because:
   - It auto-determines the optimal number of clusters.
   - It handles noise (episodes that do not fit any cluster) gracefully.
   - It captures clusters of varying density (some topics are broad, some are niche).
4. Assigns each episode to a cluster (or marks as noise).
5. For each cluster, extracts the most-representative chunk texts using TF-IDF keyword extraction.
6. Uses OpenRouter LLM to generate a short human-readable label from the top TF-IDF terms + sample chunk texts.
7. Stores results in `topic_clusters` (with `source = "auto"`) and `episode_topics`.

### Cluster Refresh

- Triggered daily at 3am via APScheduler.
- Also available as a manual "Refresh clusters" button in the admin UI.
- On refresh: deletes all `source = "auto"` rows from `topic_clusters` and their `episode_topics` entries. Re-clusters from scratch. `source = "manual"` rows are preserved.

### Pre-defined Topics

User creates a topic with a label ("Nazis"). System:
1. Embeds the label text.
2. Computes cosine distance between the label embedding and each episode's average embedding.
3. Tags episodes with distance < 0.35 to the topic.
4. Stores as `source = "manual"` in `topic_clusters`.

---

## Files to Create/Modify

| File | Change |
|---|---|
| `app/models/topic.py` | New: `TopicCluster`, `EpisodeTopic` models |
| `app/services/clustering.py` | New: HDBSCAN clustering + topic extraction logic |
| `app/services/rag.py` | New: RAG query → embedding → LLM → response |
| `app/routers/api_insights.py` | New: API endpoints for topics, comparison, RAG |
| `app/templates/insights.html` | New: Insights tab template |
| `app/templates/portal_insights.html` | New: Portal insights template |
| `app/routers/ui.py` | Add `/insights` route |
| `app/portal_server.py` | Add portal insights route |
| `app/main.py` | Add clustering scheduled job, register router |
| `app/templates/base.html` | Add "Insights" nav link |
| `app/templates/portal_search.html` | Add "Insights" nav link to portal |

---

## Dependencies to Add

```
scikit-learn  >= 1.3   (HDBSCAN, TF-IDF)
```

HDBSCAN is included in scikit-learn since 1.3. No separate package needed.

---

## Cost Estimate (OpenRouter)

Per RAG question:
- Embedding (query vector): ~$0.0001
- LLM response (GPT-4o-mini, ~500 tokens): ~$0.0005
- **Total: < $0.001 per question**

Clustering label generation (once per night):
- ~20 clusters x ~200 tokens each = $0.002 per run

---

## Decisions Made

- **Clustering cadence**: Daily at 3am + manual "Refresh" button
- **Old cluster cleanup**: Wipe all `source = "auto"` on re-cluster, keep manual topics intact
- **Portal scoping**: Global clustering, filtered at query time by `podcast_ids`
