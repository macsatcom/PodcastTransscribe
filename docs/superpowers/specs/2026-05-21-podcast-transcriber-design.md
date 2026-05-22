# Podcast Transcription and Search — System Design

## Overview

A self-hosted web application that subscribes to podcast RSS feeds, automatically
downloads and transcribes episodes using OpenRouter AI models, generates summaries,
and provides full-text + semantic search across all transcribed content.

## Architecture

```
docker-compose.yml
├── web (single Python FastAPI process)
│   ├── Web UI — HTMX + Alpine.js + Tailwind
│   ├── REST API
│   ├── Source Adapters (pluggable: RSS, future Audiobookshelf)
│   ├── OpenRouter client (transcription, summarization, embeddings)
│   ├── Search Engine (FTS + vector)
│   └── APScheduler (background jobs: polling, transcription pipeline)
└── db (PostgreSQL 16 + pgvector)
```

### Why This Stack

- **FastAPI** — native async, excellent for IO-bound transcription pipeline,
  built-in OpenAPI docs
- **HTMX + Alpine.js** — server-rendered HTML avoids JS build pipeline; Alpine
  handles client-side interactions (dropdowns, modals, toggles)
- **PostgreSQL + pgvector** — multilingual full-text search (`tsvector`) +
  vector similarity search in one database, no extra services
- **APScheduler** — in-process job scheduling; Redis/Celery overkill for 20
  podcasts polling every 6–12 hours

## Data Model

### Core Tables

**`podcasts`**
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| title | TEXT | |
| author | TEXT | |
| description | TEXT | |
| cover_url | TEXT | |
| language | TEXT | Detected or configured (e.g. `danish`, `english`) |
| auto_process | BOOLEAN | Auto-transcribe new episodes? |
| created_at | TIMESTAMPTZ | |
| updated_at | TIMESTAMPTZ | |

**`source_configs`**
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| podcast_id | UUID FK → podcasts | |
| source_type | TEXT | `rss`, `audiobookshelf` (future) |
| url | TEXT | RSS URL / API endpoint |
| config_json | JSONB | Type-specific config (polling interval, auth, etc.) |
| enabled | BOOLEAN | |
| last_polled_at | TIMESTAMPTZ | |

**`episodes`**
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| podcast_id | UUID FK → podcasts | |
| guid | TEXT | RSS GUID (unique per podcast) |
| title | TEXT | |
| description | TEXT | |
| audio_url | TEXT | |
| duration_seconds | INT | |
| published_at | TIMESTAMPTZ | |
| status | TEXT | `new` → `downloading` → `transcribing` → `summarizing` → `indexing` → `ready` / `error` |
| error_message | TEXT | |
| created_at | TIMESTAMPTZ | |

**`transcripts`**
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| episode_id | UUID FK → episodes (unique) | |
| full_text | TEXT | Complete transcription text |
| detected_language | TEXT | |
| summary | TEXT | LLM-generated summary |
| timestamps_json | JSONB | Array of `[{start, end, text}]` |
| tsvector | TSVECTOR | PostgreSQL FTS index |
| created_at | TIMESTAMPTZ | |

**`transcript_chunks`**
| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| transcript_id | UUID FK → transcripts | |
| chunk_index | INT | Order within transcript |
| text | TEXT | Chunk text (~500 words, ~50 word overlap) |
| embedding | VECTOR(1536) | OpenAI-compatible embedding dimension |
| created_at | TIMESTAMPTZ | |

**`settings`**
| Column | Type | Notes |
|--------|------|-------|
| key | TEXT PK | `transcription_model`, `summarization_model`, `embedding_model`, `openrouter_api_key` |
| value | TEXT | |

### Indexes

- `transcripts.tsvector` — GIN index for FTS
- `transcript_chunks.embedding` — IVFFlat index for approximate nearest neighbor search
- `episodes(podcast_id, status)` — pipeline queries
- `episodes(podcast_id, guid)` — deduplication

## Pipeline — Episode Processing

```
RSS Poll (APScheduler, configurable per source)
  │
  ├── Fetch feed, parse <item> elements
  ├── Deduplicate by (podcast_id, guid)
  ├── Create episode row (status=new)
  │
  └── If podcast.auto_process=True:
        Enqueue episode for pipeline

Episode Pipeline (triggered automatically or manually):

    status=new
        │
        ▼
    ┌──────────────┐
    │ Download      │
    │ audio         │
    └──────┬───────┘
           │ success
           ▼
    ┌──────────────┐
    │ Transcribe    │  ◄── OpenRouter Whisper model
    │ via API       │
    └──────┬───────┘
           │ success
           ▼
    ┌──────────────┐
    │ Summarize     │  ◄── OpenRouter LLM model
    │               │
    └──────┬───────┘
           │ success
           ▼
    ┌──────────────┐
    │ Index chunks  │  ◄── Split + embed via OpenRouter
    │               │
    └──────┬───────┘
           │ success
           ▼
    ┌──────────────┐
    │ ready         │
    └──────────────┘

Any step → status=error + error_message logged.
```

### Transcription

- Audio sent to OpenRouter using the configured transcription model
  (e.g. `openai/whisper-1`)
- Response includes full text with timestamped segments
- Raw text stored in `transcripts.full_text`, segments in `transcripts.timestamps_json`
- Language auto-detected from transcript (or from API response)

### Summarization

- Full transcript text sent to OpenRouter LLM (configurable model)
- Prompt: summarize the episode in 3–5 paragraphs in the transcript's language
- Summary stored in `transcripts.summary`

### Chunking & Embedding

- Transcript split into overlapping chunks (~500 words, ~50 word overlap)
- Each chunk embedded via OpenRouter embedding model
- Chunks + vectors stored in `transcript_chunks`

## Search

### Full-Text Search

Uses PostgreSQL `tsvector` / `tsquery` with language-specific configuration:

```sql
SELECT ts_headline($language, ft.full_text,
  phraseto_tsquery($language, $query),
  'StartSel=<mark>, StopSel=</mark>, MaxWords=60, MinWords=20')
FROM transcripts ft
JOIN episodes e ON e.id = ft.episode_id
WHERE ft.tsvector @@ phraseto_tsquery($language, $query)
  AND ($podcast_ids IS NULL OR e.podcast_id = ANY($podcast_ids))
  AND ($episode_ids IS NULL OR e.id = ANY($episode_ids))
ORDER BY ts_rank(...) DESC;
```

- Language determined per podcast or per transcript
- `<mark>` tags rendered as highlighted text in UI

### Semantic Search

```sql
SELECT chunk.text, chunk.chunk_index,
       chunk.embedding <=> $query_vector AS distance,
       e.title, e.published_at, p.title AS podcast_title
FROM transcript_chunks chunk
JOIN transcripts t ON t.id = chunk.transcript_id
JOIN episodes e ON e.id = t.episode_id
JOIN podcasts p ON p.id = e.podcast_id
WHERE ($podcast_ids IS NULL OR e.podcast_id = ANY($podcast_ids))
  AND ($episode_ids IS NULL OR e.id = ANY($episode_ids))
ORDER BY chunk.embedding <=> $query_vector ASC
LIMIT 20;
```

- Query text embedded via same OpenRouter embedding model
- Results sorted by cosine distance (lower = more similar)

### Search UI Behavior

- Default: search all content
- Optional filter: Podcast series (multi-select)
  - When series selected: Episode dropdown (multi-select) populates
- Filters apply to both FTS and semantic searches
- Results: podcast cover + title, episode title, date, highlighted snippet, relevance indicator

## Web UI — Views

**Dashboard (`/`)** — Grid of podcast cards with cover art, latest episode status.
"Add Podcast" button. Status badges.

**Podcast Detail (`/podcasts/{id}`)** — Metadata, auto-process toggle. Episode list
with status badges and "Process Now" action. "Process All Pending" button.

**Episode View (`/episodes/{id}`)** — Summary card. Transcript with timestamps.
Search terms highlighted when navigated from search results.

**Search (`/search`)** — Text input. Toggle: Natural language / Exact phrase.
Filter: Podcast multi-select → Episode multi-select. Result cards with highlighted
snippet. Click navigates to Episode View.

**Admin / Settings (`/admin`)** — OpenRouter API key. Model selection
(Transcription, Summarization, Embedding). Source management. Job history.

## Source Adapters

```
BaseSourceAdapter (ABC)
├── discover_new(podcast_id, source_config) → list[EpisodeMetadata]
├── fetch_audio(episode) → local path or stream

RSSSourceAdapter           ← Phase 1
AudiobookshelfSourceAdapter ← Phase 2 (future)
```

Each adapter translates its source's data model into canonical `EpisodeMetadata`.
Adding a new source type means implementing the adapter interface.

## OpenRouter Integration

- Single API key for all AI operations
- Three configurable model slots:
  - **Transcription:** e.g. `openai/whisper-1`
  - **Summarization:** e.g. `anthropic/claude-3.5-sonnet`, `openai/gpt-4o`
  - **Embedding:** e.g. `openai/text-embedding-3-small`
- Models selectable from admin UI

## Audio File Storage

- Stream download → pipe to OpenRouter API where possible, avoiding full local storage
- Fallback: temp file in Docker volume, deleted after transcription

## Docker Compose

```yaml
services:
  web:
    build: .
    ports: ["8000:8000"]
    volumes: ["audio_cache:/tmp/audio"]
    depends_on: [db]
    environment:
      DATABASE_URL: postgresql+asyncpg://podcast:podcast@db/podcast_transcription_search

  db:
    image: pgvector/pgvector:pg16
    volumes: ["pgdata:/var/lib/postgresql/data"]
    environment:
      POSTGRES_DB: podcast_transcription_search
      POSTGRES_USER: podcast
      POSTGRES_PASSWORD: podcast
```

## Error Handling

- Failed steps: `episode.status = error` + `error_message` — retry button reprocesses from failed step
- OpenRouter failures: exponential backoff (3 retries), then mark error
- RSS poll failures: logged, no cascade
- Temp audio cleaned by daily housekeeping job

## Non-Goals (Phase 1)

- Audio playback in browser (future)
- User accounts / multi-user (future)
- Audiobookshelf integration (future)
- Podcast discovery/search (manual RSS URL entry only)

## Future Architecture Hooks

- **Multiple source types:** `BaseSourceAdapter` interface
- **Multi-user:** `user_id` FK ready on podcasts
- **Audio playback:** timestamps_json enables click-to-seek
- **Export:** Transcript + summary as plain text, SRT, or Markdown
