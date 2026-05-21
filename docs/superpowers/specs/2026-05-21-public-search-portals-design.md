# Public Search Portals — Design

## Overview

A system for exposing branded, public-facing search portals for specific
podcasts. Each portal runs on its own port and provides full search + transcript
access scoped to one or more podcasts, with custom background images and
styling.

## Architecture

```
Main app (port 8002) — internal admin tool
├── Portal management in Admin UI
├── Subprocess manager (start/stop portals)
│
├── Portal 1 (port 9001) — "Vild med Vildt Naturligt"
│   ├── GET  /              → Branded search page
│   ├── GET  /api/search    → Scoped FTS + semantic search
│   ├── GET  /api/episodes  → Episode list for podcast
│   └── GET  /api/episodes/{id} → Full transcript
│
└── Portal 2 (port 9002) — "Something Else"
    └── ...

Shared: PostgreSQL database, portal_images Docker volume
```

## Data Model

### New table: `portals`

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| title | TEXT | Display title |
| slug | TEXT | URL-safe version of title |
| port | INT | Unique port number |
| podcast_ids | JSONB | Array of podcast UUIDs |
| background_image | TEXT | Local file path in volume |
| secondary_image | TEXT | Optional second image |
| description | TEXT | Optional short description |
| enabled | BOOL | Whether portal should be running |
| created_at | TIMESTAMPTZ | |

## API Endpoints (Internal Admin)

### Portals CRUD

- `GET /api/portals` — list all portals with running status
- `POST /api/portals` — create portal (title, port, podcast_ids)
- `PUT /api/portals/{id}` — update portal config
- `DELETE /api/portals/{id}` — delete portal (stops if running)

### Portal Control

- `POST /api/portals/{id}/start` — spawn subprocess
- `POST /api/portals/{id}/stop` — kill subprocess
- `POST /api/portals/{id}/upload-image` — upload background image (multipart)

### Portal Server Endpoints (on portal's port)

- `GET /` — Branded HTML page
- `GET /api/search?q=...` — Scoped FTS + semantic search
- `GET /api/episodes?podcast_id=...` — Episode list
- `GET /api/episodes/{id}` — Episode with transcript + summary

## Portal Subprocess

Each portal runs as a separate uvicorn process spawned by the main app:

```python
proc = await asyncio.create_subprocess_exec(
    sys.executable, "-m", "uvicorn",
    "app.portal_server:create_app",
    "--host", "0.0.0.0",
    "--port", str(portal.port),
    env={**os.environ, "PORTAL_ID": str(portal.id)},
)
```

The portal server (`app/portal_server.py`) reads its config from the database
using the `PORTAL_ID` env var, creates a minimal FastAPI app with scoped search
and branded templates.

## Images & Storage

- Docker volume `portal_images` mounted at `/app/portal_images/`
- Uploaded files: `/app/portal_images/<slug>-bg.jpg`
- Served via `StaticFiles` mount at `/static/portal_images/`
- Fallback: podcast cover art used if no portal image

## Admin UI

New section in the Admin page (`/admin`) below OpenRouter settings:

- **Portal list** — title, port, status indicator (running/stopped), podcast count
- **Create portal** — title input, port input, podcast multi-select
- **Edit portal** — all fields editable, image upload, start/stop buttons

## Branded Search Page

The public portal page is a single HTML page with:

- Full-screen background image or gradient fallback
- Title + description centered
- Search bar prominent in the hero area
- Results with podcast cover art, snippet highlighting, score
- Click-through to full transcript view
- Simple, clean, mobile-responsive layout

## Process Management

- On main app startup: read all `enabled` portals, spawn subprocess for each
- Admin UI: start/stop buttons toggle subprocess
- If portal subprocess exits unexpectedly, it's logged (auto-restart optional)
- Portal status tracked in-memory dict in main app

## Non-Goals

- Authentication on portals (public by design)
- Multiple pages per portal (single-page search app)
- Real-time updates / WebSocket

## Files to Create/Modify

**Create:**
- `app/models/portal.py` — Portal model
- `app/routers/api_portals.py` — Portal CRUD + control endpoints
- `app/portal_server.py` — Portal FastAPI app factory
- `app/templates/portal_search.html` — Branded search page
- `app/templates/portal_episode.html` — Branded episode view

**Modify:**
- `app/main.py` — Import portal router, startup portal processes
- `app/templates/admin.html` — Portal management UI
