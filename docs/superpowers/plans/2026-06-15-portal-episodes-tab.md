# Portal Episodes Tab — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tilføj en "Episodes" tab på portal-forsiden, der viser en flad kronologisk liste af alle transkriberede episoder i portalen, med link til fulde transcripts.

**Architecture:** `GET /api/episodes` udvides med `podcast_ids`-param (komma-separerede UUIDs) og JOINer med `podcasts`-tabellen for at inkludere `podcast_title` i responset. I `portal_home.html` tilføjes en tredje tab med lazy-loaded episodeliste og "Load more"-paginering via Alpine.js.

**Tech Stack:** Python/FastAPI, SQLAlchemy async, Jinja2, Alpine.js

---

### Task 1: Udvid `GET /api/episodes` med `podcast_ids`-param

**Files:**
- Modify: `app/routers/api_episodes.py`

- [ ] **Step 1: Tilføj import af `Podcast`-model**

  I toppen af `app/routers/api_episodes.py`, tilføj import:

  ```python
  from app.models.podcast import Podcast
  ```

- [ ] **Step 2: Opdater `list_episodes`-funktionens signatur**

  Erstat den eksisterende `list_episodes`-funktion (linjer 15–51) med nedenstående. Ændringer:
  - Tilføj `podcast_ids: str | None = None`
  - JOINer `Podcast` når `podcast_ids` er angivet
  - Tilføjer `podcast_title` til hvert element i responset

  ```python
  @router.get("")
  async def list_episodes(
      podcast_id: UUID | None = None,
      podcast_ids: str | None = None,
      status: str | None = None,
      media_type: str | None = None,
      limit: int = Query(default=200, ge=1, le=500),
      offset: int = Query(default=0, ge=0),
      db: AsyncSession = Depends(get_db),
  ):
      use_podcast_ids = podcast_ids is not None and podcast_ids.strip() != ""
      if use_podcast_ids:
          ids = [UUID(i.strip()) for i in podcast_ids.split(",") if i.strip()]
          query = (
              select(Episode, Podcast.title.label("podcast_title"))
              .join(Podcast, Podcast.id == Episode.podcast_id)
              .where(Episode.podcast_id.in_(ids))
          )
      else:
          query = select(Episode, None)

      if podcast_id:
          query = query.where(Episode.podcast_id == podcast_id)
      if status:
          if status == "processing":
              query = query.where(Episode.status.in_(["downloading", "transcribing", "summarizing", "indexing"]))
          else:
              query = query.where(Episode.status == status)
      if media_type:
          query = query.where(Episode.media_type == media_type)
      query = query.order_by(Episode.published_at.desc())
      if offset:
          query = query.offset(offset)
      query = query.limit(limit)
      result = await db.execute(query)
      rows = result.all()
      queued_ids = {str(eid) for eid in episode_queue.get_queued_ids()}

      def serialize(e, podcast_title):
          return {
              "id": str(e.id),
              "podcast_id": str(e.podcast_id),
              "podcast_title": podcast_title,
              "title": e.title,
              "description": e.description,
              "duration_seconds": e.duration_seconds,
              "published_at": e.published_at.isoformat() if e.published_at else None,
              "status": e.status,
              "error_message": e.error_message,
              "model_used": e.model_used,
              "processing_seconds": e.processing_seconds,
              "cost": e.cost,
              "media_type": e.media_type,
              "abs_item_id": e.abs_item_id,
              "abs_episode_id": e.abs_episode_id,
              "chapter_index": e.chapter_index,
              "queued": str(e.id) in queued_ids,
          }

      if use_podcast_ids:
          return [serialize(row.Episode, row.podcast_title) for row in rows]
      else:
          return [serialize(row.Episode, None) for row in rows]
  ```

  **Bemærk:** Når `podcast_ids` bruges, returnerer SQLAlchemy rækker med navngivne kolonner (`row.Episode`, `row.podcast_title`). Uden `podcast_ids` returneres skalarer direkte, men vi bruger samme `select(Episode, None)`-mønster for konsistens — `None` i SELECT giver `row.Episode` + `row[1] = None`.

  Faktisk er det enklere at lave to separate queries. Her er den endelige form der virker korrekt:

  ```python
  @router.get("")
  async def list_episodes(
      podcast_id: UUID | None = None,
      podcast_ids: str | None = None,
      status: str | None = None,
      media_type: str | None = None,
      limit: int = Query(default=200, ge=1, le=500),
      offset: int = Query(default=0, ge=0),
      db: AsyncSession = Depends(get_db),
  ):
      use_podcast_ids = podcast_ids is not None and podcast_ids.strip() != ""

      if use_podcast_ids:
          ids = [UUID(i.strip()) for i in podcast_ids.split(",") if i.strip()]
          query = (
              select(Episode, Podcast.title.label("podcast_title"))
              .join(Podcast, Podcast.id == Episode.podcast_id)
              .where(Episode.podcast_id.in_(ids))
          )
          if status:
              if status == "processing":
                  query = query.where(Episode.status.in_(["downloading", "transcribing", "summarizing", "indexing"]))
              else:
                  query = query.where(Episode.status == status)
          if media_type:
              query = query.where(Episode.media_type == media_type)
          query = query.order_by(Episode.published_at.desc())
          if offset:
              query = query.offset(offset)
          query = query.limit(limit)
          result = await db.execute(query)
          rows = result.all()
          queued_ids = {str(eid) for eid in episode_queue.get_queued_ids()}
          return [
              {
                  "id": str(r.Episode.id),
                  "podcast_id": str(r.Episode.podcast_id),
                  "podcast_title": r.podcast_title,
                  "title": r.Episode.title,
                  "description": r.Episode.description,
                  "duration_seconds": r.Episode.duration_seconds,
                  "published_at": r.Episode.published_at.isoformat() if r.Episode.published_at else None,
                  "status": r.Episode.status,
                  "error_message": r.Episode.error_message,
                  "model_used": r.Episode.model_used,
                  "processing_seconds": r.Episode.processing_seconds,
                  "cost": r.Episode.cost,
                  "media_type": r.Episode.media_type,
                  "abs_item_id": r.Episode.abs_item_id,
                  "abs_episode_id": r.Episode.abs_episode_id,
                  "chapter_index": r.Episode.chapter_index,
                  "queued": str(r.Episode.id) in queued_ids,
              }
              for r in rows
          ]

      # Original path (no podcast_ids) — unchanged behaviour
      query = select(Episode)
      if podcast_id:
          query = query.where(Episode.podcast_id == podcast_id)
      if status:
          if status == "processing":
              query = query.where(Episode.status.in_(["downloading", "transcribing", "summarizing", "indexing"]))
          else:
              query = query.where(Episode.status == status)
      if media_type:
          query = query.where(Episode.media_type == media_type)
      query = query.order_by(Episode.published_at.desc())
      if offset:
          query = query.offset(offset)
      query = query.limit(limit)
      result = await db.execute(query)
      episodes = result.scalars().all()
      queued_ids = {str(eid) for eid in episode_queue.get_queued_ids()}
      return [
          {
              "id": str(e.id),
              "podcast_id": str(e.podcast_id),
              "podcast_title": None,
              "title": e.title,
              "description": e.description,
              "duration_seconds": e.duration_seconds,
              "published_at": e.published_at.isoformat() if e.published_at else None,
              "status": e.status,
              "error_message": e.error_message,
              "model_used": e.model_used,
              "processing_seconds": e.processing_seconds,
              "cost": e.cost,
              "media_type": e.media_type,
              "abs_item_id": e.abs_item_id,
              "abs_episode_id": e.abs_episode_id,
              "chapter_index": e.chapter_index,
              "queued": str(e.id) in queued_ids,
          }
          for e in episodes
      ]
  ```

- [ ] **Step 3: Verificer at filen er syntaktisk korrekt**

  ```bash
  UV_PROJECT_ENVIRONMENT="/tmp/opencode/pts-venv" uv run python -c "import app.routers.api_episodes"
  ```

  Forventet: ingen output (ingen fejl).

- [ ] **Step 4: Commit**

  ```bash
  git add app/routers/api_episodes.py
  git commit -m "feat(api): add podcast_ids param to GET /api/episodes"
  ```

---

### Task 2: Tests for `podcast_ids`-param

**Files:**
- Modify: `tests/integration/test_api_episodes.py` (find eksisterende tests, eller opret ny fil)

Tjek om filen allerede eksisterer:
```bash
ls tests/integration/
```

- [ ] **Step 1: Skriv failing integration-test**

  Tilføj til `tests/integration/test_api_episodes.py` (opret filen hvis den ikke eksisterer, ellers append):

  ```python
  import pytest
  from httpx import AsyncClient, ASGITransport
  from app.main import app
  from app.database import get_db
  from tests.conftest import test_engine, override_get_db


  @pytest.fixture(autouse=True)
  def _override(monkeypatch):
      app.dependency_overrides[get_db] = override_get_db
      yield
      app.dependency_overrides.clear()


  @pytest.mark.asyncio
  async def test_list_episodes_podcast_ids_returns_podcast_title(db_session, seed_episode_done):
      """podcast_ids param returnerer podcast_title i responset."""
      ep, podcast = seed_episode_done
      async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
          r = await client.get(f"/api/episodes?podcast_ids={podcast.id}&status=done")
      assert r.status_code == 200
      data = r.json()
      assert len(data) == 1
      assert data[0]["podcast_title"] == podcast.title
      assert data[0]["id"] == str(ep.id)


  @pytest.mark.asyncio
  async def test_list_episodes_podcast_ids_filters_to_done(db_session, seed_episode_done, seed_episode_new):
      """status=done filter virker med podcast_ids."""
      ep_done, podcast = seed_episode_done
      async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
          r = await client.get(f"/api/episodes?podcast_ids={podcast.id}&status=done")
      assert r.status_code == 200
      ids = [e["id"] for e in r.json()]
      assert str(ep_done.id) in ids
      assert str(seed_episode_new[0].id) not in ids


  @pytest.mark.asyncio
  async def test_list_episodes_without_podcast_ids_still_works(db_session, seed_episode_done):
      """Eksisterende podcast_id (singular) param stadig virker uændret."""
      ep, podcast = seed_episode_done
      async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
          r = await client.get(f"/api/episodes?podcast_id={podcast.id}")
      assert r.status_code == 200
      data = r.json()
      assert any(e["id"] == str(ep.id) for e in data)
      # podcast_title er None i det eksisterende kald
      assert data[0]["podcast_title"] is None
  ```

  Fixtures `seed_episode_done` og `seed_episode_new` defineres nedenfor. Find først om `conftest.py` allerede har relevante fixtures:

  ```bash
  grep -n "seed_episode\|seed_podcast\|override_get_db" tests/conftest.py tests/integration/conftest.py 2>/dev/null || echo "not found"
  ```

  Baseret på hvad der eksisterer, tilføj disse fixtures til `tests/integration/conftest.py` (opret filen hvis den ikke eksisterer):

  ```python
  import pytest
  import uuid
  from datetime import datetime, timezone
  from sqlalchemy.ext.asyncio import AsyncSession
  from app.models.episode import Episode
  from app.models.podcast import Podcast


  @pytest.fixture
  async def seed_episode_done(db_session: AsyncSession):
      podcast = Podcast(
          id=uuid.uuid4(),
          title="Test Podcast",
          abs_item_id="abs-item-1",
          media_type="podcast",
      )
      db_session.add(podcast)
      await db_session.flush()
      ep = Episode(
          id=uuid.uuid4(),
          podcast_id=podcast.id,
          guid="guid-done-1",
          title="Done Episode",
          audio_url="http://example.com/ep1.mp3",
          published_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
          status="done",
          abs_item_id="abs-item-1",
          media_type="podcast",
      )
      db_session.add(ep)
      await db_session.commit()
      return ep, podcast


  @pytest.fixture
  async def seed_episode_new(db_session: AsyncSession, seed_episode_done):
      _, podcast = seed_episode_done
      ep = Episode(
          id=uuid.uuid4(),
          podcast_id=podcast.id,
          guid="guid-new-1",
          title="New Episode",
          audio_url="http://example.com/ep2.mp3",
          published_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
          status="new",
          abs_item_id="abs-item-1",
          media_type="podcast",
      )
      db_session.add(ep)
      await db_session.commit()
      return ep, podcast
  ```

  **Kør testen og verificer at den fejler** (fordi `podcast_title` ikke returneres endnu — men Task 1 er allerede implementeret, så de bør passere):

  ```bash
  UV_PROJECT_ENVIRONMENT="/tmp/opencode/pts-venv" DATABASE_URL="postgresql+asyncpg://podcast:podcast@172.18.0.2/podcast_transcription_search_test" uv run pytest tests/integration/test_api_episodes.py -v
  ```

  Forventet: alle tre tests PASS (Task 1 er allerede implementeret).

- [ ] **Step 2: Kør alle tests**

  ```bash
  UV_PROJECT_ENVIRONMENT="/tmp/opencode/pts-venv" DATABASE_URL="postgresql+asyncpg://podcast:podcast@172.18.0.2/podcast_transcription_search_test" uv run pytest -q
  ```

  Forventet: alle eksisterende tests stadig PASS.

- [ ] **Step 3: Commit**

  ```bash
  git add tests/integration/test_api_episodes.py tests/integration/conftest.py
  git commit -m "test(api): add tests for podcast_ids param in GET /api/episodes"
  ```

---

### Task 3: Episodes-tab i `portal_home.html`

**Files:**
- Modify: `app/templates/portal_home.html`

Alle ændringer i denne task er i `portal_home.html`. Der er tre steder der skal ændres:

**A) Tab-knap** — i tab-bar-sektionen (linje ~150 i skabelonen):

- [ ] **Step 1: Tilføj Episodes-tab-knap**

  Find denne blok i `portal_home.html`:
  ```html
        <button class="tab-btn" :class="tab==='search' ? 'active' : ''" @click="setTab('search')">Search</button>
        <button class="tab-btn" :class="tab==='insights' ? 'active' : ''" @click="setTab('insights')">Insights</button>
  ```

  Erstat med:
  ```html
        <button class="tab-btn" :class="tab==='search' ? 'active' : ''" @click="setTab('search')">Search</button>
        <button class="tab-btn" :class="tab==='insights' ? 'active' : ''" @click="setTab('insights')">Insights</button>
        <button class="tab-btn" :class="tab==='episodes' ? 'active' : ''" @click="setTab('episodes')">Episodes</button>
  ```

**B) Episodes-panel** — tilføj efter Insights-panelblokken (efter `<!-- Episode modal (Topics) -->` men inden `</div></div>`):

- [ ] **Step 2: Tilføj Episodes-panel HTML**

  Find denne linje i `portal_home.html`:
  ```html
      <!-- Episode modal (Topics) -->
  ```

  Indsæt følgende blok INDEN den linje (dvs. Episodes-panelet kommer mellem Insights-tab og modal):

  ```html
      <!-- ───────── EPISODES TAB ───────── -->
      <div x-show="tab==='episodes'" x-cloak>
        <div x-show="episodesLoading && episodes.length === 0" style="color:var(--text-dim);padding:32px;text-align:center;">
          <span class="spinner"></span> Loading episodes...
        </div>
        <div x-show="!episodesLoading && episodes.length === 0 && episodesLoaded" class="empty">
          No transcribed episodes yet.
        </div>
        <div style="display:flex;flex-direction:column;gap:10px;">
          <template x-for="ep in episodes" :key="ep.id">
            <a :href="'/episodes/' + ep.id" class="result-card">
              <div class="result-header">
                <div class="result-body">
                  <div class="result-title-row">
                    <span class="result-title" x-text="ep.title"></span>
                  </div>
                  <div class="result-meta" style="margin-top:4px;">
                    <span x-text="ep.podcast_title" style="color:var(--text-secondary);"></span>
                    <template x-if="ep.published_at">
                      <span x-text="' · ' + new Date(ep.published_at).toLocaleDateString('da-DK', {year:'numeric',month:'short',day:'numeric'})"></span>
                    </template>
                    <template x-if="ep.duration_seconds">
                      <span x-text="' · ' + formatDuration(ep.duration_seconds)"></span>
                    </template>
                  </div>
                  <template x-if="ep.summary_excerpt">
                    <div class="result-snippet" x-text="ep.summary_excerpt" style="margin-top:6px;"></div>
                  </template>
                </div>
              </div>
            </a>
          </template>
        </div>
        <div x-show="episodesHasMore" style="text-align:center;margin-top:20px;">
          <button @click="loadEpisodes()" :disabled="episodesLoading" class="btn btn-ghost btn-sm">
            <span x-show="episodesLoading"><span class="spinner"></span></span>
            <span x-text="episodesLoading ? 'Loading...' : 'Load more'"></span>
          </button>
        </div>
      </div>

  ```

**C) Alpine.js state og metoder** — i `portalHome()`-funktionen i `<script>`-blokken:

- [ ] **Step 3: Tilføj episodes-state til `return`-objektet**

  Find denne linje i `<script>`-blokken (i `return {`):
  ```js
        // Insights state
  ```

  Indsæt følgende INDEN den linje:
  ```js
        // Episodes state
        episodes: [], episodesLoaded: false, episodesOffset: 0,
        episodesHasMore: false, episodesLoading: false,

  ```

- [ ] **Step 4: Tilføj `loadEpisodes()` og `formatDuration()` til `return`-objektet**

  Find denne metode i `return`-objektet:
  ```js
        async askQuestion() {
  ```

  Indsæt følgende INDEN den metode:
  ```js
        async loadEpisodes() {
          if (this.episodesLoading) return;
          this.episodesLoading = true;
          const PAGE = 50;
          try {
            const ids = (this.portal.podcast_ids || []).join(',');
            const params = new URLSearchParams({ status: 'done', limit: PAGE, offset: this.episodesOffset });
            if (ids) params.set('podcast_ids', ids);
            const r = await fetch('/api/episodes?' + params);
            const data = await r.json();
            const enriched = data.map(ep => ({
              ...ep,
              summary_excerpt: ep.transcript?.summary
                ? ep.transcript.summary.slice(0, 150) + (ep.transcript.summary.length > 150 ? '\u2026' : '')
                : null,
            }));
            this.episodes = this.episodes.concat(enriched);
            this.episodesOffset += data.length;
            this.episodesHasMore = data.length === PAGE;
          } catch(e) { console.error(e); }
          this.episodesLoading = false;
          this.episodesLoaded = true;
        },

        formatDuration(secs) {
          if (!secs) return '';
          const h = Math.floor(secs / 3600);
          const m = Math.floor((secs % 3600) / 60);
          if (h > 0) return `${h}t ${m}m`;
          return `${m}m`;
        },

  ```

- [ ] **Step 5: Udvid `setTab()` til at lazy-loade episodes**

  Find den eksisterende `setTab`-metode:
  ```js
        setTab(name) {
          this.tab = name;
          history.replaceState(null, '', '#' + name);
          if (name === 'insights' && this.topics.length === 0) this.loadTopics();
        },
  ```

  Erstat med:
  ```js
        setTab(name) {
          this.tab = name;
          history.replaceState(null, '', '#' + name);
          if (name === 'insights' && this.topics.length === 0) this.loadTopics();
          if (name === 'episodes' && !this.episodesLoaded) this.loadEpisodes();
        },
  ```

- [ ] **Step 6: Udvid `init()` til at understøtte `#episodes` URL-hash**

  Find den eksisterende `init`-metode:
  ```js
        async init() {
          const hash = window.location.hash.replace('#', '');
          if (hash === 'insights') { this.tab = 'insights'; await this.loadTopics(); }
        },
  ```

  Erstat med:
  ```js
        async init() {
          const hash = window.location.hash.replace('#', '');
          if (hash === 'insights') { this.tab = 'insights'; await this.loadTopics(); }
          if (hash === 'episodes') { this.tab = 'episodes'; await this.loadEpisodes(); }
        },
  ```

- [ ] **Step 7: Kør fuld testsuite for at verificere ingen regression**

  ```bash
  UV_PROJECT_ENVIRONMENT="/tmp/opencode/pts-venv" DATABASE_URL="postgresql+asyncpg://podcast:podcast@172.18.0.2/podcast_transcription_search_test" uv run pytest -q
  ```

  Forventet: alle tests PASS.

- [ ] **Step 8: Commit**

  ```bash
  git add app/templates/portal_home.html
  git commit -m "feat(portal): add Episodes tab with paginated episode list"
  ```

---

### Task 4: Afslut — push til remote

- [ ] **Step 1: Verificer git log**

  ```bash
  git log --oneline -5
  ```

  Forventede commits i toppen:
  - `feat(portal): add Episodes tab with paginated episode list`
  - `test(api): add tests for podcast_ids param in GET /api/episodes`
  - `feat(api): add podcast_ids param to GET /api/episodes`

- [ ] **Step 2: Push**

  ```bash
  git push origin master
  ```

---

## Bemærkninger

**API-respons og summary_excerpt:** `GET /api/episodes`-endpointet returnerer ikke `transcript.summary` i list-endpointet — kun i `GET /api/episodes/{id}`. `summary_excerpt` dannes derfor på klienten som `null` (da summary ikke er inkluderet i list-responset). Hvis summary-excerpt-visning er vigtig, kan det tilføjes som en separat udvidelse af Task 1 — men det kræver JOIN med `transcripts`-tabellen og øger kompleksiteten. For nu vises ingen summary_excerpt i episodekortene (feltet er `null`). Dette er YAGNI-korrekt for første version.

**Alternativ:** Hvis summary_excerpt ønskes, tilføjes til Task 1:
- JOIN `Transcript` i `podcast_ids`-stien
- Tilføj `"summary_excerpt": r.Transcript.summary[:150] + "…" if r.Transcript and r.Transcript.summary and len(r.Transcript.summary) > 150 else (r.Transcript.summary if r.Transcript else None)` til responset
