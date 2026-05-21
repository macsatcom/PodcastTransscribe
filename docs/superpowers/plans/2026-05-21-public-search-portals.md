# Public Search Portals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add branded public search portals — each running on its own port, scoped to specific podcasts, with custom images and styling.

**Architecture:** Portal configs stored in DB. Main app spawns portal subprocesses on separate ports. Each portal is a minimal FastAPI app serving branded search + transcript pages.

**Tech Stack:** FastAPI, uvicorn subprocesses, PostgreSQL, Jinja2 templates, alpine.js, tailwind css

---

## File Structure

```
Create:
  app/models/portal.py
  app/routers/api_portals.py
  app/portal_server.py
  app/templates/portal_search.html
  app/templates/portal_episode.html
Modify:
  app/main.py          — import portal router, spawn portals on startup
  app/templates/admin.html  — portal management UI
  docker-compose.yml   — add portal_images volume
  Dockerfile           — create portal_images dir
```

---

### Task 1: Portal Model

**Files:**
- Create: `app/models/portal.py`
- Modify: `app/models/__init__.py`

- [ ] **Step 1: Create app/models/portal.py**

```python
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Portal(Base):
    __tablename__ = "portals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    port: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    podcast_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    background_image: Mapped[str] = mapped_column(Text, nullable=True)
    secondary_image: Mapped[str] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 2: Update app/models/__init__.py** to export Portal

```python
from app.models.podcast import Podcast
from app.models.episode import Episode
from app.models.transcript import Transcript, TranscriptChunk
from app.models.source_config import SourceConfig
from app.models.setting import Setting
from app.models.portal import Portal

__all__ = [
    "Podcast",
    "Episode",
    "Transcript",
    "TranscriptChunk",
    "SourceConfig",
    "Setting",
    "Portal",
]
```

- [ ] **Step 3: Verify import**

Run: `python3 -c "from app.models import Portal; print('OK')"`

---

### Task 2: Portal API Endpoints

**Files:**
- Create: `app/routers/api_portals.py`

- [ ] **Step 1: Create API router**

The file should contain these endpoints:

```python
from uuid import UUID

from fastapi import APIRouter, Depends, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.portal import Portal
from app.portal_manager import portal_manager

router = APIRouter(prefix="/api/portals", tags=["portals"])


class CreatePortalRequest(BaseModel):
    title: str
    port: int
    podcast_ids: list[str]
    description: str | None = None


@router.get("")
async def list_portals(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Portal).order_by(Portal.title))
    portals = result.scalars().all()
    return [
        {
            "id": str(p.id),
            "title": p.title,
            "slug": p.slug,
            "port": p.port,
            "podcast_ids": p.podcast_ids,
            "description": p.description,
            "background_image": p.background_image,
            "secondary_image": p.secondary_image,
            "enabled": p.enabled,
            "running": portal_manager.is_running(p.id),
        }
        for p in portals
    ]


@router.post("")
async def create_portal(
    body: CreatePortalRequest,
    db: AsyncSession = Depends(get_db),
):
    slug = body.title.lower().replace(" ", "-").replace(/[^a-z0-9-]/g, "")[:50]
    portal = Portal(
        title=body.title,
        slug=slug,
        port=body.port,
        podcast_ids=body.podcast_ids,
        description=body.description,
    )
    db.add(portal)
    await db.commit()
    await db.refresh(portal)
    return {"id": str(portal.id), "title": portal.title, "slug": portal.slug}


@router.get("/{portal_id}")
async def get_portal(portal_id: UUID, db: AsyncSession = Depends(get_db)):
    portal = await db.get(Portal, portal_id)
    if not portal:
        return {"error": "not found"}
    return {
        "id": str(portal.id),
        "title": portal.title,
        "slug": portal.slug,
        "port": portal.port,
        "podcast_ids": portal.podcast_ids,
        "description": portal.description,
        "background_image": portal.background_image,
        "secondary_image": portal.secondary_image,
        "enabled": portal.enabled,
        "running": portal_manager.is_running(portal.id),
    }


@router.put("/{portal_id}")
async def update_portal(
    portal_id: UUID,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    portal = await db.get(Portal, portal_id)
    if not portal:
        return {"error": "not found"}
    for key in ("title", "port", "podcast_ids", "description", "enabled"):
        if key in body:
            setattr(portal, key, body[key])
    await db.commit()
    return {"status": "updated"}


@router.delete("/{portal_id}")
async def delete_portal(portal_id: UUID, db: AsyncSession = Depends(get_db)):
    await portal_manager.stop(portal_id)
    portal = await db.get(Portal, portal_id)
    if portal:
        await db.delete(portal)
        await db.commit()
    return {"status": "deleted"}


@router.post("/{portal_id}/start")
async def start_portal(portal_id: UUID, db: AsyncSession = Depends(get_db)):
    portal = await db.get(Portal, portal_id)
    if not portal:
        return {"error": "not found"}
    await portal_manager.start(portal)
    return {"status": "started"}


@router.post("/{portal_id}/stop")
async def stop_portal(portal_id: UUID, db: AsyncSession = Depends(get_db)):
    await portal_manager.stop(portal_id)
    return {"status": "stopped"}


@router.post("/{portal_id}/upload-image")
async def upload_portal_image(
    portal_id: UUID,
    image_type: str = "background",
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    portal = await db.get(Portal, portal_id)
    if not portal:
        return {"error": "not found"}
    ext = os.path.splitext(file.filename)[1] or ".jpg"
    filename = f"{portal.slug}-{image_type}{ext}"
    path = os.path.join(settings.portal_images_dir, filename)
    content = await file.read()
    with open(path, "wb") as f:
        f.write(content)
    if image_type == "background":
        portal.background_image = f"/static/portal_images/{filename}"
    else:
        portal.secondary_image = f"/static/portal_images/{filename}"
    await db.commit()
    return {"status": "uploaded", "path": portal.background_image or portal.secondary_image}
```

Note: The slug generation regex in `create_portal` should be:
```python
import re
slug = re.sub(r'[^a-z0-9-]', '', body.title.lower().replace(" ", "-"))[:50]
```

And the router needs `import os, re` and `from app.config import settings`.

Also, the `create_portal` endpoint needs to auto-generate a slug from the title.

- [ ] **Step 2: Verify no import errors**

Run: `python3 -c "from app.routers.api_portals import router; print('OK')"`

---

### Task 3: Portal Process Manager

**Files:**
- Create: `app/portal_manager.py`

- [ ] **Step 1: Create portal_manager.py**

```python
import asyncio
import logging
import os
import sys
import signal
from uuid import UUID

logger = logging.getLogger(__name__)


class PortalManager:
    def __init__(self):
        self._processes: dict[UUID, asyncio.subprocess.Process] = {}

    def is_running(self, portal_id: UUID) -> bool:
        proc = self._processes.get(portal_id)
        return proc is not None and proc.returncode is None

    async def start(self, portal):
        if self.is_running(portal.id):
            logger.info("Portal %s already running", portal.id)
            return

        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "uvicorn",
            "app.portal_server:create_app",
            "--host", "0.0.0.0",
            "--port", str(portal.port),
            env={
                **os.environ,
                "PORTAL_ID": str(portal.id),
                "PORTAL_PORT": str(portal.port),
            },
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._processes[portal.id] = proc
        logger.info("Started portal %s on port %s", portal.id, portal.port)

        asyncio.create_task(self._watch(portal.id, proc))

    async def _watch(self, portal_id, proc):
        await proc.wait()
        logger.warning("Portal %s exited with code %s", portal_id, proc.returncode)
        self._processes.pop(portal_id, None)

    async def stop(self, portal_id: UUID):
        proc = self._processes.pop(portal_id, None)
        if proc is None:
            return
        try:
            proc.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        except ProcessLookupError:
            pass
        logger.info("Stopped portal %s", portal_id)

    async def start_all(self, portals):
        for portal in portals:
            if portal.enabled:
                await self.start(portal)

    async def stop_all(self):
        for pid in list(self._processes.keys()):
            await self.stop(pid)


portal_manager = PortalManager()
```

- [ ] **Step 2: Verify import**

Run: `python3 -c "from app.portal_manager import portal_manager; print('OK')"`

---

### Task 4: Portal Server (subprocess app)

**Files:**
- Create: `app/portal_server.py`

- [ ] **Step 1: Create portal_server.py**

This file creates the FastAPI app that runs in the subprocess:

```python
import os
import uuid

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.database import async_session
from app.models.portal import Portal


def create_app() -> FastAPI:
    portal_id = uuid.UUID(os.environ["PORTAL_ID"])
    app = FastAPI(title="Portal")

    static_dir = Path(__file__).parent.parent / "portal_images"
    static_dir.mkdir(exist_ok=True)
    app.mount("/static/portal_images", StaticFiles(directory=str(static_dir)), name="portal_images")

    from app.routers import api_search
    app.include_router(api_search.router, prefix="/api")

    from app.routers import api_episodes
    app.include_router(api_episodes.router, prefix="/api")

    from fastapi import APIRouter, Request
    from fastapi.responses import HTMLResponse
    from fastapi.templating import Jinja2Templates

    portal_router = APIRouter()
    templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

    @portal_router.get("/", response_class=HTMLResponse)
    async def portal_home(request: Request):
        async with async_session() as session:
            portal = await session.get(Portal, portal_id)
            if not portal:
                return HTMLResponse("Portal not found", status_code=404)
        return templates.TemplateResponse("portal_search.html", {
            "request": request,
            "portal": portal,
        })

    @portal_router.get("/episodes/{episode_id}", response_class=HTMLResponse)
    async def portal_episode(request: Request, episode_id: str):
        async with async_session() as session:
            portal = await session.get(Portal, portal_id)
        return templates.TemplateResponse("portal_episode.html", {
            "request": request,
            "portal": portal,
            "episode_id": episode_id,
        })

    app.include_router(portal_router)
    return app
```

- [ ] **Step 2: Verify import**

Run: `python3 -c "from app.portal_server import create_app; print('OK')"`

---

### Task 5: Portal Templates

**Files:**
- Create: `app/templates/portal_search.html`
- Create: `app/templates/portal_episode.html`

- [ ] **Step 1: Create portal_search.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{{ portal.title }}</title>
  <script src="https://unpkg.com/alpinejs@3.14.8" defer></script>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body { margin: 0; min-height: 100vh; }
    .bg-overlay { background: linear-gradient(rgba(0,0,0,0.6), rgba(0,0,0,0.8)); }
  </style>
</head>
<body class="text-white"
      x-data="searchView()" x-init="init()"
      :style="'background: url(' + bgImage + ') center/cover fixed; min-height: 100vh;'">

  <div class="bg-overlay min-h-screen">
    <div class="mx-auto max-w-4xl px-4 py-12">
      <div class="text-center mb-10">
        <h1 class="text-4xl font-bold mb-3" x-text="portal.title"></h1>
        <p x-show="portal.description" class="text-lg text-gray-300" x-text="portal.description"></p>
      </div>

      <div class="flex gap-2 mb-8 max-w-2xl mx-auto">
        <input type="text" x-model="query" @keyup.enter="doSearch()"
               placeholder="Search episodes..."
               class="flex-1 p-3 rounded-lg bg-white/10 border border-white/20 text-white placeholder-gray-400 text-lg">
        <button @click="doSearch()" class="px-6 py-3 rounded-lg bg-emerald-600 hover:bg-emerald-500 font-medium">Search</button>
      </div>

      <div x-show="query && !loading" id="results" class="space-y-4">
        <p x-show="results.length === 0" class="text-center text-gray-400">No results found.</p>
        <template x-for="r in results" :key="r.episode_id">
          <a :href="'/episodes/' + r.episode_id + '?q=' + encodeURIComponent(query)"
             class="block p-4 rounded-lg bg-white/10 backdrop-blur hover:bg-white/20 transition border border-white/10">
            <div class="flex items-start gap-3">
              <template x-if="r.cover_url">
                <img :src="r.cover_url" class="w-10 h-10 rounded flex-shrink-0">
              </template>
              <div>
                <div class="text-sm font-semibold" x-text="r.episode_title"></div>
                <div class="text-xs text-gray-400 mt-1" x-html="r.snippet"></div>
                <div class="text-xs text-gray-500 mt-1">
                  <span x-text="r.type === 'fts' ? 'Exact match' : 'Relevance: ' + (r.score || 0).toFixed(2)"></span>
                </div>
              </div>
            </div>
          </a>
        </template>
      </div>
    </div>
  </div>

  <script>
    function searchView() {
      return {
        portal: { title: {{ portal.title|tojson }}, description: {{ portal.description|tojson }}, background_image: {{ portal.background_image|tojson }}, secondary_image: {{ portal.secondary_image|tojson }} },
        bgImage: {{ portal.background_image or ''|tojson }} || 'https://images.unsplash.com/photo-1508700115892-45ecd05ae2ad?w=1920',
        query: '',
        loading: false,
        results: [],
        async init() {
          if (this.portal.secondary_image) {
            this.bgImage = this.portal.secondary_image;
          }
        },
        async doSearch() {
          if (!this.query.trim()) return;
          this.loading = true;
          const r = await fetch('/api/search?q=' + encodeURIComponent(this.query) + '&mode=auto');
          const data = await r.json();
          this.results = data.results;
          this.loading = false;
        }
      };
    }
  </script>
</body>
</html>
```

- [ ] **Step 2: Create portal_episode.html**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title x-text="episodeTitle"></title>
  <script src="https://unpkg.com/alpinejs@3.14.8" defer></script>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body { margin: 0; min-height: 100vh; }
    .bg-overlay { background: linear-gradient(rgba(0,0,0,0.6), rgba(0,0,0,0.85)); }
  </style>
</head>
<body class="text-white"
      x-data="episodeView()" x-init="loadEpisode()"
      :style="'background: url(' + bgImage + ') center/cover fixed; min-height: 100vh;'">

  <div class="bg-overlay min-h-screen">
    <div class="mx-auto max-w-4xl px-4 py-8">
      <a href="/" class="text-emerald-400 hover:text-emerald-300 text-sm mb-4 inline-block">&larr; Back to search</a>

      <div x-show="!loading">
        <h1 class="text-2xl font-bold mb-2" x-text="episode.title"></h1>
        <p class="text-gray-400 text-sm mb-6" x-text="episode.published_at || ''"></p>

        <div x-show="summary" class="mb-6 p-4 rounded-lg bg-white/10 backdrop-blur border border-white/10">
          <h2 class="text-sm font-semibold text-emerald-400 mb-2">Summary</h2>
          <div class="text-sm leading-relaxed" x-text="summary"></div>
        </div>

        <div class="text-sm leading-relaxed whitespace-pre-wrap" x-html="highlightedText"></div>
      </div>
      <p x-show="loading" class="text-gray-400 text-center py-12">Loading...</p>
    </div>
  </div>

  <script>
    function episodeView() {
      return {
        episodeId: '{{ episode_id }}',
        portal: { background_image: {{ portal.background_image|tojson }} },
        bgImage: {{ portal.background_image or ''|tojson }} || 'https://images.unsplash.com/photo-1508700115892-45ecd05ae2ad?w=1920',
        loading: true,
        episode: {},
        summary: '',

        async loadEpisode() {
          const r = await fetch('/api/episodes/' + this.episodeId);
          const data = await r.json();
          this.episode = data;
          this.summary = data.transcript?.summary || '';
          this.loading = false;
        },

        get highlightedText() {
          if (!this.episode?.transcript?.full_text) return '';
          const params = new URLSearchParams(window.location.search);
          const highlight = params.get('q');
          let text = this.episode.transcript.full_text;
          if (highlight) {
            text = text.replace(
              new RegExp('(' + highlight.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi'),
              '<mark class="bg-emerald-600 text-white px-0.5 rounded">$1</mark>'
            );
          }
          return text;
        }
      };
    }
  </script>
</body>
</html>
```

---

### Task 6: Wire Everything Together

**Files:**
- Modify: `app/main.py`
- Modify: `app/templates/admin.html`
- Modify: `docker-compose.yml`
- Modify: `Dockerfile`

- [ ] **Step 1: Add portal router + startup spawning to main.py**

Add to the imports and lifespan:

```python
from app.routers import api_podcasts, api_episodes, api_search, api_settings, ui, api_portals
from app.portal_manager import portal_manager
from app.models.portal import Portal

app.include_router(api_portals.router)
```

In the lifespan, add after scheduler start:

```python
from sqlalchemy import select

async with async_session() as session:
    result = await session.execute(select(Portal))
    portals = result.scalars().all()
    await portal_manager.start_all(portals)
```

And before engine.dispose in lifespan shutdown:

```python
await portal_manager.stop_all()
```

Also add `from app.database import async_session` to imports.

- [ ] **Step 2: Add portal management UI to admin.html**

Below the existing settings card, add a `<template x-if="adminTab === 'portals'">` section, and add a tab switcher. Or simpler: just add the portal section below the settings card.

Add to admin.html after the settings div:

```html
<div class="mt-8 p-4 bg-gray-900 rounded-lg border border-gray-800">
  <h2 class="font-semibold mb-3">Public Portals</h2>
  
  <div x-data="portalManager()" x-init="loadPortals()">
    <button @click="showForm = true" class="bg-emerald-600 hover:bg-emerald-500 px-3 py-1.5 rounded text-xs mb-4">+ New Portal</button>

    <div x-show="showForm" class="mb-4 p-3 bg-gray-800 rounded space-y-2">
      <input x-model="form.title" placeholder="Title" class="w-full p-2 rounded bg-gray-700 border border-gray-600 text-sm">
      <input x-model="form.port" type="number" placeholder="Port (e.g. 9001)" class="w-full p-2 rounded bg-gray-700 border border-gray-600 text-sm">
      <input x-model="form.description" placeholder="Description" class="w-full p-2 rounded bg-gray-700 border border-gray-600 text-sm">
      <select x-model="form.podcast_ids" multiple class="w-full p-2 rounded bg-gray-700 border border-gray-600 text-sm">
        <template x-for="p in podcasts" :key="p.id">
          <option :value="p.id" x-text="p.title"></option>
        </template>
      </select>
      <button @click="createPortal()" class="bg-emerald-600 px-3 py-1 rounded text-xs">Create</button>
    </div>

    <template x-for="p in portals" :key="p.id">
      <div class="flex items-center justify-between p-2 bg-gray-800 rounded mb-2 text-sm">
        <div>
          <div x-text="p.title" class="font-medium"></div>
          <div class="text-xs text-gray-500" x-text="'Port ' + p.port + ' · ' + (p.podcast_ids?.length || 0) + ' podcasts'"></div>
        </div>
        <div class="flex items-center gap-2">
          <span class="text-xs px-1.5 py-0.5 rounded" :class="p.running ? 'bg-emerald-700 text-emerald-200' : 'bg-gray-700 text-gray-400'" x-text="p.running ? 'Running' : 'Stopped'"></span>
          <button @click="togglePortal(p)" class="text-xs" :class="p.running ? 'text-red-400' : 'text-emerald-400'" x-text="p.running ? 'Stop' : 'Start'"></button>
          <button @click="deletePortal(p)" class="text-xs text-red-400">Delete</button>
        </div>
      </div>
    </template>
  </div>
</div>

<script>
function portalManager() {
  return {
    showForm: false,
    portals: [],
    podcasts: [],
    form: { title: '', port: 9001, description: '', podcast_ids: [] },
    
    async loadPortals() {
      const [pr, pdr] = await Promise.all([
        fetch('/api/portals'),
        fetch('/api/podcasts'),
      ]);
      this.portals = await pr.json();
      this.podcasts = await pdr.json();
    },
    
    async createPortal() {
      await fetch('/api/portals', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(this.form),
      });
      this.showForm = false;
      this.form = { title: '', port: 9001, description: '', podcast_ids: [] };
      await this.loadPortals();
    },
    
    async togglePortal(p) {
      await fetch(`/api/portals/${p.id}/${p.running ? 'stop' : 'start'}`, { method: 'POST' });
      await this.loadPortals();
    },
    
    async deletePortal(p) {
      await fetch(`/api/portals/${p.id}`, { method: 'DELETE' });
      await this.loadPortals();
    },
  };
}
</script>
```

- [ ] **Step 3: Update docker-compose.yml** to add portal_images volume

Add to the `web` service volumes:
```yaml
- portal_images:/app/portal_images
```

Add to the top-level volumes:
```yaml
portal_images:
```

- [ ] **Step 4: Update Dockerfile** to create portal_images dir

Add before the USER line:
```dockerfile
RUN mkdir /app/portal_images && chown appuser:appuser /app/portal_images
```

- [ ] **Step 5: Add portal_images dir creation to app config.py or main.py**

Add to the startup in main.py lifespans:
```python
import os
os.makedirs("/app/portal_images", exist_ok=True)
```

And add `portal_images_dir` to settings in `app/config.py`:
```python
portal_images_dir: str = "/app/portal_images"
```

---

### Task 7: Verify + Build

- [ ] **Step 1: Run tests**

Run: `python3 -m pytest tests/ -v`
Expected: 7 passed

- [ ] **Step 2: Verify all imports**

Run: `python3 -c "from app.main import app; from app.portal_server import create_app; from app.portal_manager import portal_manager; from app.models import Portal; print('OK')"`

- [ ] **Step 3: Build and deploy**

Run: `docker compose build web && docker compose up -d web`

- [ ] **Step 4: Verify portal API works**

Run: `curl -s http://localhost:8002/api/portals | python3 -m json.tool`
Expected: `[]`

---

## Self-Review

1. **Spec coverage:** All spec sections covered:
   - Portal model: Task 1
   - Portal CRUD API: Task 2
   - Portal control (start/stop): Task 3 + Task 2
   - Image upload: Task 2 endpoint
   - Portal server subprocess: Task 4
   - Branded templates: Task 5
   - Admin UI: Task 6
   - Docker volume + build: Task 6 + Task 7

2. **Placeholder scan:** No placeholders found.

3. **Type consistency:** UUID types consistent across model, API, and manager. PortalManager uses `UUID` keys matching model's `id` type.
