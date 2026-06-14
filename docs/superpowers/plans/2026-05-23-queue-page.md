# Queue Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a unified queue/job-log page showing episode processing status across all podcasts.

**Architecture:** New `GET /api/queue` endpoint returns episodes grouped by status (running, queued, error, done) with podcast titles. New Jinja2 template with Alpine.js polling renders four status sections. No DB changes.

**Tech Stack:** FastAPI, SQLAlchemy 2.0, Jinja2, Alpine.js, Tailwind CSS

---

### Task 1: API endpoint `GET /api/queue`

**Files:**
- Create: `app/routers/api_queue.py`

- [ ] **Step 1: Create `app/routers/api_queue.py`**

```python
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.database import get_db
from app.models.episode import Episode
from app.models.podcast import Podcast

router = APIRouter(prefix="/api", tags=["queue"])

RUNNING_STATUSES = {"downloading", "transcribing", "summarizing", "indexing"}


def _serialize(episode: Episode) -> dict:
    return {
        "id": str(episode.id),
        "podcast_id": str(episode.podcast_id),
        "podcast_title": episode.podcast.title if episode.podcast else None,
        "title": episode.title,
        "status": episode.status,
        "error_message": episode.error_message,
        "processing_seconds": episode.processing_seconds,
        "created_at": episode.created_at.isoformat() if episode.created_at else None,
    }


@router.get("/queue")
async def get_queue(db: AsyncSession = Depends(get_db)):
    query = (
        select(Episode)
        .options(joinedload(Episode.podcast))
        .order_by(Episode.created_at.desc())
    )
    result = await db.execute(query)
    episodes = result.scalars().all()

    items = [_serialize(e) for e in episodes]

    running = [e for e in items if e["status"] in RUNNING_STATUSES]
    queued = [e for e in items if e["status"] == "new"]
    error = [e for e in items if e["status"] == "error"]
    done = [e for e in items if e["status"] == "ready"]

    running.sort(key=lambda e: e["created_at"] or "", reverse=True)
    queued.sort(key=lambda e: e["created_at"] or "")
    error.sort(key=lambda e: e["created_at"] or "", reverse=True)
    done.sort(key=lambda e: e["created_at"] or "", reverse=True)
    done = done[:50]

    return {
        "running": running,
        "queued": queued,
        "error": error,
        "done": done,
        "counts": {
            "running": len(running),
            "queued": len(queued),
            "error": len(error),
            "done": len(done),
        },
    }
```

- [ ] **Step 2: Verify the file reads correctly**

Read the new file and check syntax: `python -c "import ast; ast.parse(open('app/routers/api_queue.py').read()); print('OK')"`

---

### Task 2: Register the new router

**Files:**
- Modify: `app/main.py`

- [ ] **Step 1: Add import and include_router**

Edit `app/main.py:45`:

```
-from app.routers import api_podcasts, api_episodes, api_search, api_settings, ui, api_portals
+from app.routers import api_podcasts, api_episodes, api_queue, api_search, api_settings, ui, api_portals
```

Edit `app/main.py` after `app.include_router(api_episodes.router)` (line 48):

```
+app.include_router(api_queue.router)
```

---

### Task 3: Add UI route `GET /queue`

**Files:**
- Modify: `app/routers/ui.py`

- [ ] **Step 1: Add `/queue` route**

Edit `app/routers/ui.py`, add after the `/admin` route (line 36):

```python
@router.get("/queue", response_class=HTMLResponse)
async def queue_page(request: Request):
    return templates.TemplateResponse(request, "queue.html")
```

---

### Task 4: Create queue template

**Files:**
- Create: `app/templates/queue.html`

- [ ] **Step 1: Create `app/templates/queue.html`**

```html
{% extends "base.html" %}
{% block content %}
<div x-data="queueView()" x-init="loadQueue(); startPolling()">
  <div class="flex items-center justify-between mb-6">
    <h1 class="text-2xl font-bold">Queue</h1>
    <div class="flex items-center gap-3 text-sm">
      <span x-show="counts.running > 0" class="flex items-center gap-1 text-blue-400">
        <svg class="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
        </svg>
        <span x-text="counts.running"></span> running
      </span>
      <span class="text-yellow-400" x-show="counts.queued > 0" x-text="counts.queued + ' queued'"></span>
      <span class="text-red-400" x-show="counts.error > 0" x-text="counts.error + ' failed'"></span>
      <span class="text-gray-500" x-text="counts.done + ' completed'"></span>
    </div>
  </div>

  <div class="space-y-6">
    <!-- Running -->
    <div x-show="running.length > 0">
      <h2 class="text-sm font-semibold text-blue-400 mb-2 flex items-center gap-2">
        <svg class="animate-spin h-3 w-3" viewBox="0 0 24 24" fill="none">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
        </svg>
        Running (<span x-text="running.length"></span>)
      </h2>
      <div class="space-y-1">
        <template x-for="ep in running" :key="ep.id">
          <a :href="'/episodes/' + ep.id" class="flex items-center justify-between p-2.5 bg-blue-900/20 border border-blue-800/40 rounded-lg hover:bg-blue-900/30 transition text-sm">
            <div class="min-w-0 flex-1">
              <span class="font-medium truncate" x-text="ep.title"></span>
              <span class="text-gray-500 ml-2" x-text="ep.podcast_title"></span>
            </div>
            <span class="text-xs px-2 py-0.5 rounded bg-blue-700 text-blue-200 flex-shrink-0 ml-2" x-text="ep.status"></span>
          </a>
        </template>
      </div>
    </div>

    <!-- Queued -->
    <div x-show="queued.length > 0">
      <h2 class="text-sm font-semibold text-yellow-400 mb-2 flex items-center gap-2">
        <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"/>
          <polyline points="12 6 12 12 16 14"/>
        </svg>
        In Queue (<span x-text="queued.length"></span>)
      </h2>
      <div class="space-y-1">
        <template x-for="ep in queued" :key="ep.id">
          <a :href="'/episodes/' + ep.id" class="flex items-center justify-between p-2.5 bg-gray-800/50 border border-gray-700/50 rounded-lg hover:bg-gray-800 transition text-sm">
            <div class="min-w-0 flex-1">
              <span class="font-medium truncate" x-text="ep.title"></span>
              <span class="text-gray-500 ml-2" x-text="ep.podcast_title"></span>
            </div>
            <span class="text-xs px-2 py-0.5 rounded bg-yellow-700 text-yellow-200 flex-shrink-0 ml-2">queued</span>
          </a>
        </template>
      </div>
    </div>

    <!-- Error -->
    <div x-show="error.length > 0">
      <h2 class="text-sm font-semibold text-red-400 mb-2 flex items-center gap-2">
        <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"/>
          <line x1="15" y1="9" x2="9" y2="15"/>
          <line x1="9" y1="9" x2="15" y2="15"/>
        </svg>
        Failed (<span x-text="error.length"></span>)
      </h2>
      <div class="space-y-1">
        <template x-for="ep in error" :key="ep.id">
          <a :href="'/episodes/' + ep.id" class="flex items-center justify-between p-2.5 bg-red-900/20 border border-red-800/40 rounded-lg hover:bg-red-900/30 transition text-sm">
            <div class="min-w-0 flex-1">
              <span class="font-medium truncate" x-text="ep.title"></span>
              <span class="text-gray-500 ml-2" x-text="ep.podcast_title"></span>
              <p x-show="ep.error_message" class="text-xs text-red-400 mt-0.5 truncate" x-text="ep.error_message"></p>
            </div>
            <span class="text-xs px-2 py-0.5 rounded bg-red-700 text-red-200 flex-shrink-0 ml-2">failed</span>
          </a>
        </template>
      </div>
    </div>

    <!-- Completed -->
    <div x-show="done.length > 0">
      <h2 class="text-sm font-semibold text-gray-500 mb-2 flex items-center gap-2">
        <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="20 6 9 17 4 12"/>
        </svg>
        Completed (<span x-text="done.length"></span>)
      </h2>
      <div class="space-y-1">
        <template x-for="ep in done" :key="ep.id">
          <a :href="'/episodes/' + ep.id" class="flex items-center justify-between p-2.5 bg-gray-800/30 border border-gray-700/30 rounded-lg hover:bg-gray-800/50 transition text-sm">
            <div class="min-w-0 flex-1">
              <span class="font-medium truncate" x-text="ep.title"></span>
              <span class="text-gray-500 ml-2" x-text="ep.podcast_title"></span>
            </div>
            <span class="text-xs px-2 py-0.5 rounded bg-gray-700 text-gray-300 flex-shrink-0 ml-2">completed</span>
          </a>
        </template>
      </div>
    </div>

    <!-- Empty state -->
    <div x-show="totalItems() === 0" class="text-center py-12 text-gray-500">
      <p class="text-lg">No episodes yet</p>
      <p class="text-sm mt-1">Add a podcast to get started.</p>
    </div>
  </div>
</div>

<script>
function queueView() {
  return {
    running: [],
    queued: [],
    error: [],
    done: [],
    counts: { running: 0, queued: 0, error: 0, done: 0 },
    pollTimer: null,

    totalItems() {
      return this.running.length + this.queued.length + this.error.length + this.done.length;
    },

    async loadQueue() {
      try {
        const r = await fetch('/api/queue');
        const data = await r.json();
        this.running = data.running;
        this.queued = data.queued;
        this.error = data.error;
        this.done = data.done;
        this.counts = data.counts;
      } catch (e) {
        console.error('Failed to load queue', e);
      }
    },

    startPolling() {
      this.loadQueue();
      this.pollTimer = setInterval(() => {
        this.loadQueue();
        if (this.counts.running === 0 && this.counts.queued === 0) {
          clearInterval(this.pollTimer);
          this.pollTimer = null;
        }
      }, 2000);
    }
  };
}
</script>
{% endblock %}
```

---

### Task 5: Add menu link

**Files:**
- Modify: `app/templates/base.html`

- [ ] **Step 1: Add "Queue" to the navigation bar**

Edit `app/templates/base.html`, add between Dashboard and Search (after line 13):

```html
    <a href="/queue" class="hover:text-emerald-300 text-sm">Queue</a>
```

---

### Task 6: Verify it works

- [ ] **Step 1: Run the app and check the queue page**

```bash
cd /home/ksn/git-ksn/podcast-transcription-search && python -c "
from app.routers.api_queue import router
print('api_queue router OK')
from app.main import app
print('app startup OK')
"
```

- [ ] **Step 2: Start the dev server and check the page renders**

```bash
cd /home/ksn/git-ksn/podcast-transcription-search && uvicorn app.main:app --reload --port 8000
```
Open `http://localhost:8000/queue` and verify the page loads with the navigation link visible.
