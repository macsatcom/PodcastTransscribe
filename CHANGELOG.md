# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.18.3] - 2026-05-30

### Fixed

- **Semantic search returned no results** — the default cosine-distance
  threshold was 0.40, calibrated against chunk-to-chunk distances. Real
  query-to-document distances with `text-embedding-3-large` are typically
  0.45–0.65 for relevant content; nearly every genuine result was filtered
  out before it could reach the UI. Default raised to 0.65. The threshold
  remains configurable via `semantic_distance_threshold` in the `settings`
  table without a code change.

## [0.18.2] - 2026-05-30

### Fixed

- **Podcast filter dropdowns show only podcasts with transcribed content** —
  the search and insights podcast filters previously listed all podcasts
  regardless of whether any episodes had been transcribed. Both dropdowns now
  filter on `ready_count > 0` so only podcasts with at least one ready episode
  appear as options.

## [0.18.1] - 2026-05-30

### Fixed

- **Migration crash on startup** — replaced `ivfflat` with `hnsw` for the
  3072-dim embedding index. `ivfflat` has a hard 2000-dimension ceiling;
  `text-embedding-3-large` produces 3072-dim vectors, causing Alembic to crash
  at startup and preventing the app from accepting connections. The index
  creation is now wrapped in a `DO/EXCEPTION` block so older pgvector builds
  degrade gracefully to a sequential scan rather than failing hard. No data
  loss — the failed DDL transaction rolled back cleanly.

## [0.18.0] — 2026-05-30

### Search & Insights repair release

The 0.17.x search/insights stack had several architectural issues that produced
poor relevance, poor diversity, and silent failures. This release rebuilds the
retrieval and clustering layers and fixes a handful of P1 bugs.

### Added
- **Re-embedding worker** (`app/services/reembed.py`) — idempotent, resumable
  background task that re-embeds all transcripts when the embedding model
  changes. Status, estimate, trigger, and cancel endpoints under
  `/api/settings/reembed/*`. Admin UI exposes confirm modal and progress.
- **Semantic distance threshold** as a Setting (`semantic_distance_threshold`,
  default `0.40`, sweet spot `0.35`–`0.45`) with admin UI slider. Applied
  consistently across search, RAG, and clustering.
- **Alembic** baseline + delta migration. `alembic upgrade head` runs on
  application startup via the FastAPI lifespan handler.
- **Per-chunk evidence chips** with `?t=<seconds>` deep-links in the Insights
  page (topic clusters and RAG sources both surface direct timestamps).
- **MMR re-ranking** (λ=0.7) for RAG with a per-episode cap of 2, so one
  verbose episode can no longer dominate the answer context.
- **Low-confidence fallback** for RAG: when fewer than 4 chunks pass the
  distance threshold, surface the snippets directly instead of asking the LLM
  to fabricate an answer.
- **LLM-generated topic labels** via `gpt-4o-mini` with representative
  excerpts stored in `TopicCluster.representative_chunks` (JSONB).

### Changed
- **Default embedding model** is now `openai/text-embedding-3-large`
  (3072-dim, multilingual). Switching models in Settings auto-queues a full
  re-embed of every transcript.
- **Chunking** rewritten to 250-token / 40-token-overlap segment-aligned
  windows with explicit `start_time` / `end_time` metadata per chunk.
  `embed_chunks` now returns `(model, embeddings)`.
- **Semantic search** rewritten (`app/services/searcher.py`) to a
  candidate-pool + episode-aggregation pattern: top-200 chunks below threshold,
  filtered by current embedding model, aggregated to one row per episode with
  up to 3 supporting evidence chunks at ≥0.03 diversity floor.
- **Topic clustering** (`app/services/clustering.py`) rewritten to chunk-level
  HDBSCAN on normalized embeddings with euclidean distance,
  `min_cluster_size = max(3, sqrt(N)/4)`, model-filtered, with top-5
  centroid-closest representatives stored as JSONB. Prior auto-generated
  clusters are wiped before each run; manual clusters are preserved.
- **RAG citation format** is now `[Podcast — Episode title, MM:SS]` and the
  LLM is required to include the citation tag inline after each claim.
- **Sources payload** for RAG is per-chunk (snippet + start_time + citation),
  not per-episode, so the UI can render one chip per piece of evidence.
- **Pipeline** persists chunk metadata produced by the embedder rather than
  recomputing it later. Stage timeouts are now defined in `STAGE_TIMEOUTS`.
- **Insights `/topics` API** correctly filters by `podcast_id` via an inner
  join on `EpisodeTopic`+`Episode` instead of returning the global cluster set.

### Fixed (P1 audit)
- **SQL injection** closure in the search code path.
- **ABS adapter** lifecycle: now exposes `async with` context-manager semantics
  so HTTP clients are no longer leaked.
- **Pipeline stage snapshot** is captured before mutation so retries see a
  consistent view of stage state.
- **Whisper** discovery and timeout handling: explicit per-stage timeouts and
  graceful failure when the model binary cannot be located.
- Removed dead code paths and unused helpers exposed by the audit.

### Schema
- New columns on `transcript_chunks`: `embedding_model`, `embedding_dim`,
  `start_time`, `end_time`.
- `TopicCluster.embedding` widened to `Vector(3072)`; new
  `representative_chunks` (JSONB) and `source` (`auto` / `manual`) columns.
- Partial ivfflat index on `transcript_chunks.embedding` filtered to
  `embedding_dim = 3072`; expression GIN index on
  `to_tsvector('simple', full_text)`.

### Migration notes
- On first start of 0.18.0, Alembic stamps the baseline and applies the delta.
- The default embedding model changed; the re-embed worker auto-runs once on
  the first model switch. Monitor progress under Settings → Re-embedding.
- The default `semantic_distance_threshold` is `0.40`. If your previous
  deployment relied on a looser de-facto threshold, raise it temporarily under
  Settings until the new corpus has finished re-embedding.
