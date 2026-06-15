# Portal Episodes UI Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Forbedr Episodes-tabben til en kompakt, skannbar tight-list med altid synlig summary (max 4 linjer) uden backend-ændringer.

**Architecture:** Ændringen holdes 100% i `portal_home.html`: nye episodes-specifikke CSS-klasser + opdateret markup for hver episode-række + robust summary fallback (`summary_excerpt` → `description` → placeholder). Search og Insights bevares urørt, og eksisterende fetch/paginering genbruges.

**Tech Stack:** Jinja2 template, inline CSS, Alpine.js, FastAPI integration tests via pytest

---

## File Structure and Responsibilities

- **Modify:** `app/templates/portal_home.html`
  - Tilføj episodes-specifikke styles (`.episodes-list`, `.episode-row`, `.episode-head`, `.episode-meta`, `.episode-badge`, `.episode-summary`, `.line-clamp-4`)
  - Opdater Episodes-tab markup til tight-list layout
  - Tilføj Alpine helper til fallback summary clipping
- **Test (verification):**
  - `tests/integration/test_auth_portal.py`
  - `tests/integration/test_episodes_api.py`

Ingen nye filer, ingen backend-modeller, ingen API-router-ændringer.

---

### Task 1: Add Tight-List Styles for Episodes

**Files:**
- Modify: `app/templates/portal_home.html`

- [ ] **Step 1: Add line-clamp utility and episodes style block**

In `<style>` in `app/templates/portal_home.html`, append this block near existing card/result styles:

```css
    .episodes-list { display: flex; flex-direction: column; gap: 8px; }
    .episode-row {
      display: block;
      padding: 14px 16px;
      border-radius: var(--radius);
      border: 1px solid var(--border);
      background: var(--bg-card);
      color: inherit;
      text-decoration: none;
      transition: background 0.2s, border-color 0.2s;
      -webkit-backdrop-filter: blur(12px);
      backdrop-filter: blur(12px);
    }
    .episode-row:hover { background: var(--bg-card-hover); border-color: rgba(255,255,255,0.25); }
    .episode-head {
      display: flex;
      align-items: baseline;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 6px;
      flex-wrap: wrap;
    }
    .episode-title { font-size: 0.95rem; font-weight: 650; color: #fff; line-height: 1.35; }
    .episode-meta { font-size: 0.75rem; color: var(--text-dim); white-space: nowrap; }
    .episode-badge {
      display: inline-block;
      font-size: 0.688rem;
      font-weight: 600;
      color: var(--text-secondary);
      background: rgba(255,255,255,0.08);
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 2px 8px;
      margin-bottom: 6px;
    }
    .episode-summary { font-size: 0.82rem; color: var(--text-secondary); line-height: 1.5; }
    .line-clamp-4 {
      display: -webkit-box;
      -webkit-line-clamp: 4;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
```

- [ ] **Step 2: Verify template still parses with no syntax errors**

Run:

```bash
UV_PROJECT_ENVIRONMENT="/tmp/opencode/pts-venv" uv run python -c "from jinja2 import Environment, FileSystemLoader; Environment(loader=FileSystemLoader('app/templates')).get_template('portal_home.html')"
```

Expected: command exits successfully with no traceback.

- [ ] **Step 3: Commit styles change**

```bash
git add app/templates/portal_home.html
git commit -m "style(portal): add tight-list episodes styling"
```

---

### Task 2: Convert Episodes Markup to Tight-List Structure

**Files:**
- Modify: `app/templates/portal_home.html`

- [ ] **Step 1: Replace Episodes list wrapper and item card markup**

In Episodes tab block, replace current wrapper:

```html
<div style="display:flex;flex-direction:column;gap:10px;">
```

with:

```html
<div class="episodes-list">
```

Then replace each episode anchor block to this structure:

```html
<template x-for="ep in episodes" :key="ep.id">
  <a :href="'/episodes/' + ep.id" class="episode-row">
    <div class="episode-head">
      <span class="episode-title" x-text="ep.title"></span>
      <span class="episode-meta">
        <span x-show="ep.published_at" x-text="new Date(ep.published_at).toLocaleDateString('da-DK', {year:'numeric',month:'short',day:'numeric'})"></span>
        <span x-show="ep.duration_seconds" x-text="(ep.published_at ? ' · ' : '') + formatDuration(ep.duration_seconds)"></span>
      </span>
    </div>

    <div class="episode-badge" x-text="ep.podcast_title || 'Podcast'"></div>

    <div class="episode-summary line-clamp-4" x-text="episodeSummary(ep)"></div>
  </a>
</template>
```

- [ ] **Step 2: Keep loading/empty/error/load-more blocks unchanged**

Confirm these behaviors are untouched:
- loading spinner on first load
- empty state
- error + retry state
- load more button visibility with `episodesHasMore`

- [ ] **Step 3: Commit markup change**

```bash
git add app/templates/portal_home.html
git commit -m "feat(portal): switch episodes tab to compact tight-list layout"
```

---

### Task 3: Add Summary Fallback Helper in Alpine

**Files:**
- Modify: `app/templates/portal_home.html`

- [ ] **Step 1: Add `episodeSummary(ep)` method to Alpine component**

In `portalHome()` methods, add:

```js
      episodeSummary(ep) {
        if (ep?.summary_excerpt && ep.summary_excerpt.trim()) return ep.summary_excerpt;
        if (ep?.description && ep.description.trim()) {
          const d = ep.description.trim();
          return d.length > 220 ? d.slice(0, 220) + '\u2026' : d;
        }
        return 'No summary available.';
      },
```

Place it close to other formatting helpers (`formatTime`, `formatDuration`) for readability.

- [ ] **Step 2: Verify no JS/template regressions with targeted integration tests**

Run:

```bash
UV_PROJECT_ENVIRONMENT="/tmp/opencode/pts-venv" DATABASE_URL="postgresql+asyncpg://podcast:podcast@172.18.0.2/podcast_transcription_search_test" uv run pytest tests/integration/test_auth_portal.py tests/integration/test_episodes_api.py -q
```

Expected: tests pass.

- [ ] **Step 3: Commit helper and final UI polish wiring**

```bash
git add app/templates/portal_home.html
git commit -m "feat(portal): add robust episodes summary fallback rendering"
```

---

### Task 4: Final Verification and Push

**Files:**
- Verify all modified files in git history

- [ ] **Step 1: Run full test suite**

```bash
UV_PROJECT_ENVIRONMENT="/tmp/opencode/pts-venv" DATABASE_URL="postgresql+asyncpg://podcast:podcast@172.18.0.2/podcast_transcription_search_test" uv run pytest -q
```

Expected: full suite passes (existing warnings acceptable if unchanged).

- [ ] **Step 2: Inspect branch status and recent commits**

```bash
git status -sb
git log --oneline -8
```

Expected: only intended commits ahead of `origin/master`.

- [ ] **Step 3: Push**

```bash
git push origin master
```

---

## Self-Review Checklist

- Spec coverage: all selected tight-list requirements mapped to Tasks 1-3
- Placeholder scan: no TODO/TBD markers
- Type consistency: `episodeSummary(ep)` used exactly in markup; summary fallback order is explicit and matches spec
