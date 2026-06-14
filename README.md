# Podcast Transcription and Search

A self-hosted web application for subscribing to podcast RSS feeds, automatically transcribing episodes via OpenRouter AI, generating summaries, and providing full-text + semantic search across all transcribed content.

## From Personal Need to Creator Tool ##

Podcast Transcription and Search started as a personal solution: searching through hundreds of podcast episodes to find "that episode where they talked about X." Full-text search wasn't enough—you needed semantic understanding. But building it revealed something bigger.

Content creators face the same challenge daily. A podcaster with 200+ episodes wants to reference back to an old discussion, prepare for a guest return, or find thematic connections across their archive. Manually scrolling through transcripts kills momentum. Semantic search solves this.

With dual search (keyword + semantic), creators can ask natural questions: "Episodes where we discussed startup funding" or "Find the episode with that funny story about coffee." PostgreSQL FTS gives you precision; pgvector embeddings give you meaning. Together, they're powerful.

Add summarization, and a creator reviewing their own content finds gold: key takeaways, guest highlights, recurring themes—all searchable, all instant.
The tool isn't just for hosts. Co-hosts prep faster. Producers find clips. Audience members dig deeper. It's the archive search that podcasting always needed.


## Features

- **RSS Feed Subscription** — Add podcast RSS URLs, auto-detect new episodes
- **AI Transcription** — Transcribes episodes using OpenRouter models (GPT-4o-audio-mini, Whisper alternatives)
- **Summarization** — Generates episode summaries in the detected language (Danish, English, etc.)
- **Full-Text Search** — Exact phrase matching via PostgreSQL FTS with highlighted results
- **Semantic Search** — Natural language search using vector embeddings for conceptual matching
- **Search Portals** — Create branded public-facing search pages for specific podcasts, each on its own port
- **Model Selection** — Choose transcription, summarization, and embedding models via admin UI
- **Docker Deployment** — Single docker-compose setup with PostgreSQL + pgvector

## Tech Stack

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 async
- **Database:** PostgreSQL 16 + pgvector
- **AI:** OpenRouter API (transcription, LLM, embeddings)
- **UI:** Alpine.js, Tailwind CSS
- **Infrastructure:** Docker Compose

## Quick Start

### 1. Prerequisites

- Docker and Docker Compose
- An [OpenRouter](https://openrouter.ai) API key

### 2. Run

```bash
git clone https://github.com/macsatcom/podcast-transcription-search.git
cd podcast-transcription-search
export OPENROUTER_API_KEY="sk-or-v1-..."
docker compose up -d
```

### 3. Configure

1. Open `http://<your-server>:8002/admin`
2. Paste your OpenRouter API key and click "Save & Load Models"
3. Select your preferred models (defaults work well)
4. Go to Dashboard → **+ Add Podcast** → enter title + RSS URL

### 4. Usage

- **Dashboard** — Overview of all podcasts, episode counts, latest episodes
- **Search** — Dual search fields: keywords (FTS) and natural language (semantic)
- **Episode View** — Full transcript with summary, keyword highlighting
- **Admin** — API key, model selection, portal management

### 5. Public Portals

Create branded search pages exposed on separate ports:

1. Admin → Public Portals → + New Portal
2. Set title, port (e.g., 9001), select podcasts
3. Upload/set background images via URL or file
4. Start the portal
5. Reverse proxy your domain to `localhost:9001`

Ports 9000-9010 are pre-exposed in docker-compose.

## Local Whisper (Optional)

For offline transcription without OpenRouter, you can run a local Whisper service:

### CPU / NVIDIA GPU

```bash
docker compose --profile whisper up -d
```

This starts a Whisper ASR service on port 9050 using `onerahmet/openai-whisper-asr-webservice` with the `large-v3` model. First start downloads ~3GB model. Then select `local-whisper` in Admin → Transcription Model.

### AMD ROCm GPU

```bash
docker compose --profile whisper-rocm up -d
```

Uses `jjajjara/rocm-whisper-api` for AMD GPU acceleration.

### Self-hosted Whisper (remote)

Run a Whisper server on any machine (e.g. Jetson, separate server). Set the URL in Admin → Self-hosted Whisper URL and select `self-hosted-whisper` as Transcription Model.

### Model sizes

- `large-v3` (~3GB) — best accuracy, supports Danish. Requires ~6GB RAM.
- `medium` (~1.5GB) — good balance.
- `small` (~500MB) — faster, slightly less accurate.

Set `ASR_MODEL` environment variable to change model size.

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /api/podcasts` | List podcasts with episode counts |
| `POST /api/podcasts` | Add podcast |
| `GET /api/episodes` | List episodes |
| `GET /api/episodes/{id}` | Episode with transcript |
| `GET /api/search?q=&nq=` | Dual search (FTS + semantic) |
| `GET/PUT /api/settings` | Manage settings |
| `GET/POST /api/portals` | Manage public portals |

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OPENROUTER_API_KEY` | Yes | — | OpenRouter API key |
| `DATABASE_URL` | No | `postgresql+asyncpg://podcast:podcast@db/podcast_transcription_search` | Database connection |

## Optional Authentication

Authentication is disabled by default. You can enable it from the Admin UI with one username/password for the main app and one username/password per portal.

- Main app auth: Admin -> Authentication
- Portal auth: Admin -> Public Portals -> Edit portal -> Authentication

Behavior when enabled:

- Browser requests are redirected to `/login`
- API requests return `401` JSON responses
- Sessions are cookie-based and scoped (`main` vs specific portal)

Notes:

- Leave password blank in update forms to keep the existing password
- There is no public signup flow; credentials are admin-managed only

## License

MIT
