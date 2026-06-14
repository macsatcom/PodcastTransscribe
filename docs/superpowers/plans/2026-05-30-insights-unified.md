# Insights Unified Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Merge Search + Insights into a single tabbed view on both the main app and all portals, and upgrade the portal episode page to a full chunk-level transcript viewer.

**Architecture:** Tab state is driven by URL hash (`#search` / `#insights`) so deep-links and browser back/forward work without page reloads. Alpine.js manages tab switching client-side. A new `/api/episodes/{id}/chunks` endpoint exposes chunk-level transcript data with timestamps. Portal home collapses from two pages into one.

**Tech Stack:** FastAPI, SQLAlchemy async, Alpine.js 3.14, Jinja2, PostgreSQL + pgvector

---

## File Map

| File | Action |
|---|---|
| `app/routers/api_episodes.py` | Add `GET /api/episodes/{id}/chunks` |
| `app/templates/search.html` | Add Insights tab (absorbs insights.html content) |
| `app/templates/insights.html` | Remove (superseded) |
| `app/routers/ui.py` | `/insights` → redirect to `/search#insights` |
| `app/templates/portal_home.html` | New — merged portal Search+Insights tabbed page |
| `app/templates/portal_search.html` | Remove (superseded) |
| `app/templates/portal_insights.html` | Remove (superseded) |
| `app/templates/portal_episode.html` | Enhance with chunk-level transcript viewer |
| `app/portal_server.py` | `/` → `portal_home.html`; `/insights` → redirect |
| `pyproject.toml` + `CHANGELOG.md` | Bump to 0.19.0 |

---

## Task 1: Add chunks API endpoint

**Files:**
- Modify: `app/routers/api_episodes.py`

- [ ] **Step 1: Add the route** after the existing `GET /{episode_id}` handler:

```python
@router.get("/{episode_id}/chunks")
async def get_episode_chunks(episode_id: UUID, db: AsyncSession = Depends(get_db)):
    from app.models.transcript import TranscriptChunk
    result = await db.execute(
        select(Transcript).where(Transcript.episode_id == episode_id)
    )
    transcript = result.scalar_one_or_none()
    if not transcript:
        return []
    chunks_result = await db.execute(
        select(TranscriptChunk)
        .where(TranscriptChunk.transcript_id == transcript.id)
        .order_by(TranscriptChunk.chunk_index)
    )
    chunks = chunks_result.scalars().all()
    return [
        {
            "chunk_index": c.chunk_index,
            "text": c.text,
            "start_time": c.start_time,
            "end_time": c.end_time,
        }
        for c in chunks
    ]
```

- [ ] **Step 2: Smoke-test**

```bash
curl -s http://localhost:8002/api/episodes/<any-ready-episode-id>/chunks | python3 -m json.tool | head -30
```

Expected: JSON array of `{chunk_index, text, start_time, end_time}` objects (start_time may be null for pre-0.18.0 episodes).

- [ ] **Step 3: Commit**

```bash
git add app/routers/api_episodes.py
git commit -m "feat: add GET /api/episodes/{id}/chunks endpoint"
```

---

## Task 2: Merge search.html + insights.html into tabbed view

**Files:**
- Modify: `app/templates/search.html`
- Remove: `app/templates/insights.html`

- [ ] **Step 1: Replace `app/templates/search.html`** with the tabbed version (Search + Insights tabs sharing one Alpine.js scope):

The new file extends `base.html` and uses URL hash to drive the active tab. The Insights section is a verbatim lift of `insights.html`'s content, with `insightsView()` logic merged into `searchView()`.

- [ ] **Step 2: Delete superseded file**

```bash
git rm app/templates/insights.html
```

- [ ] **Step 3: Commit**

```bash
git add app/templates/search.html
git commit -m "feat: merge Search + Insights into tabbed view on main app"
```

---

## Task 3: Redirect /insights → /search#insights

**Files:**
- Modify: `app/routers/ui.py`

- [ ] **Step 1: Replace insights route with redirect**

```python
from fastapi.responses import RedirectResponse

@router.get("/insights", response_class=HTMLResponse)
async def insights_redirect():
    return RedirectResponse(url="/search#insights", status_code=302)
```

- [ ] **Step 2: Commit**

```bash
git add app/routers/ui.py
git commit -m "feat: redirect /insights to /search#insights"
```

---

## Task 4: Create portal_home.html

**Files:**
- Create: `app/templates/portal_home.html`
- Remove: `app/templates/portal_search.html`, `app/templates/portal_insights.html`

- [ ] **Step 1: Create** the merged portal page with Search | Insights tabs. Uses same dark theme, background image logic, and portal branding as the existing pages.

- [ ] **Step 2: Remove superseded templates**

```bash
git rm app/templates/portal_search.html app/templates/portal_insights.html
```

- [ ] **Step 3: Commit**

```bash
git add app/templates/portal_home.html
git commit -m "feat: merge portal search+insights into tabbed portal_home.html"
```

---

## Task 5: Update portal_server.py

**Files:**
- Modify: `app/portal_server.py`

- [ ] **Step 1: Update routes**

```python
from fastapi.responses import RedirectResponse

@portal_router.get("/", response_class=HTMLResponse)
async def portal_home(request: Request):
    ...
    return templates.TemplateResponse(
        request, "portal_home.html", context={"portal": portal},
    )

@portal_router.get("/insights", response_class=HTMLResponse)
async def portal_insights_redirect():
    return RedirectResponse(url="/#insights", status_code=302)
```

- [ ] **Step 2: Commit**

```bash
git add app/portal_server.py
git commit -m "feat: portal / serves portal_home.html; /insights redirects"
```

---

## Task 6: Enhance portal_episode.html with chunk-level transcript

**Files:**
- Modify: `app/templates/portal_episode.html`

- [ ] **Step 1: Update `loadEpisode()` to also fetch chunks**, then render chunk rows with timestamps. Fall back to `full_text` blob when all `start_time` values are null.

- [ ] **Step 2: Auto-scroll to `?t=` timestamp** by finding the closest chunk and scrolling its element into view.

- [ ] **Step 3: Commit**

```bash
git add app/templates/portal_episode.html
git commit -m "feat: portal episode page shows chunk-level transcript with timestamps"
```

---

## Task 7: Version bump

**Files:**
- Modify: `pyproject.toml`, `CHANGELOG.md`

- [ ] **Step 1: Bump version** to `0.19.0` in `pyproject.toml`

- [ ] **Step 2: Add CHANGELOG entry**

- [ ] **Step 3: Commit + tag**

```bash
git add pyproject.toml CHANGELOG.md
git commit -m "chore: release 0.19.0"
git tag v0.19.0
```
