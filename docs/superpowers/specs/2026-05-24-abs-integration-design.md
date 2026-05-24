# Audiobookshelf Integration Design

**Date:** 2026-05-24
**Status:** Approved

## Overview

Integrate the Audiobookshelf (ABS) content source from `audiobookshelf-transcribe-and-search` into the `podcast-transcription-search` project. The ABS project will be abandoned after this integration.

The dashboard will have two tabs under a unified interface:
- **Podcasts** — RSS feed-based podcasts (existing functionality)
- **Library** — Audiobookshelf content (podcasts, audiobooks, e-books)

## Data Model Changes

### Podcast (`podcasts`) — add 3 columns
| Column | Type | Description |
|--------|------|-------------|
| `abs_item_id` | Text, nullable | Audiobookshelf item ID for linking back to ABS |
| `media_type` | Text, nullable | `"podcast"`, `"book"`, or `"ebook"`. NULL for RSS items |
| `narrator` | Text, nullable | Audiobook narrator name |

### Episode (`episodes`) — add 5 columns
| Column | Type | Description |
|--------|------|-------------|
| `abs_item_id` | Text, nullable | Parent ABS item ID |
| `abs_episode_id` | Text, nullable | ABS episode/chapter identifier |
| `chapter_index` | Integer, nullable | Position within audiobook chapters |
| `media_type` | Text, nullable | Inherited from parent podcast |
| `updated_at` | DateTime(tz) | Auto-updating timestamp |

### EpisodeMetadata dataclass — add 4 fields
| Field | Type | Default |
|-------|------|---------|
| `abs_item_id` | `str \| None` | `None` |
| `abs_episode_id` | `str \| None` | `None` |
| `chapter_index` | `int \| None` | `None` |
| `media_type` | `str` | `"podcast"` |

All new columns are nullable — existing RSS data is unaffected.

## New Files

### `app/adapters/abs.py`
Port from ABS project. `ABSSourceAdapter` class:
- Uses `httpx.AsyncClient` with Bearer token auth
- `get_libraries()` — `GET /api/libraries`
- `get_library_items(library_id, media_type)` — `GET /api/libraries/{id}/items`
- `get_item(item_id, expanded)` — `GET /api/items/{id}`
- `get_play_info(item_id, episode_id)` — `POST /api/items/{id}/play`
- `check_new_episodes(podcast_item_id)` — `GET /api/podcasts/{id}/checknew`
- `discover_new(abs_item_id)` — routes by mediaType to podcast or book discovery
- `_discover_podcast_episodes()` — refresh RSS, get expanded item, iterate episodes
- `_discover_book_chapters()` — handle chapters with startOffset/endOffset durations
- `fetch_audio(audio_url)` — streaming download with 2 retries

### `app/services/abs_poller.py`
Port from ABS project:
- Polls all `SourceConfig` entries where `source_type == "abs"`
- Calls adapter for each config
- Creates Podcast + Episode rows for newly discovered items
- Sets `media_type` on both podcast and episode
- Enqueues episodes only if `auto_process == True`
- Skips e-books (no episodes/audio to transcribe)
- Scheduled every 6 hours via APScheduler

### `app/routers/api_abs.py`
Port from ABS project:
- `GET /api/abs/libraries` — proxy ABS library list
- `GET /api/abs/library/{id}/items` — browse items with transcription status
- `GET /api/abs/items/{id}` — item detail with episodes/chapters + processing status
- `GET /api/abs/items/{id}/cover` — proxy cover images
- `POST /api/abs/items/{id}/auto-process` — toggle auto_process

### `app/templates/library_detail.html`
Port from ABS project:
- Item info: cover, title, author, narrator, media type badge
- Auto-process toggle
- Episodes/chapters list with status badges
- Per-item "Transcribe" / "Retry" buttons
- Batch select + "Transcribe Selected"

## Updated Files

### `app/adapters/base.py`
Add ABS fields to `EpisodeMetadata`:
```python
abs_item_id: str | None = None
abs_episode_id: str | None = None
chapter_index: int | None = None
media_type: str = "podcast"
```

### `app/config.py`
Add 2 settings:
```python
abs_url: str = ""
abs_api_key: str = ""
```

### `app/main.py`
- Register `api_abs.router`
- Schedule `poll_abs_libraries` every 6 hours (alongside existing `poll_all_feeds`)
- Update job IDs to distinct names

### `app/routers/api_episodes.py`
- Include `media_type`, `abs_item_id`, `abs_episode_id`, `chapter_index` in serialized Episode response
- Add optional `media_type` query filter to list endpoint

### `app/routers/api_search.py`
- Add optional `media_type` query parameter
- Pass through to `search_fts()` and `search_semantic()`

### `app/routers/api_settings.py`
- Add `abs_url` and `abs_api_key` to VALID_KEYS
- Add `GET /api/settings/abs/test` — test ABS connection

### `app/routers/api_queue.py`
- Include `media_type` and `podcast_title` in serialized queue items

### `app/routers/ui.py`
- Add `GET /library/{abs_item_id}` route → `library_detail.html`

### `app/services/searcher.py`
- Add `media_type: str | None = None` parameter to both `search_fts()` and `search_semantic()`
- Add `media_type` filter in WHERE clauses and result dicts

### `app/services/pipeline.py`
- Resolve the correct adapter per episode:
  - Episodes with `podcast.source_config.source_type == "abs"` → use `ABSSourceAdapter`
  - Otherwise → use `RSSSourceAdapter`

### `app/templates/dashboard.html`
Redesign with two tabs:
- **Podcasts tab:** existing RSS podcast grid with Add/Delete
- **Library tab:** ABS browser with library selector dropdown, item cards showing cover/title/author/media-type-badge/transcription-status, checkboxes for batch selection, e-book items shown with "not transcribable" badge (no checkbox/transcribe button)

### `app/templates/admin.html`
Add Audiobookshelf section (above OpenRouter section):
- ABS URL input field
- ABS API Key input field
- "Save & Test Connection" button with status feedback
- Save also persists to server via settings API

### `app/templates/search.html`
- Add media type filter dropdown (All / Podcasts / Audiobooks)
- Display media type badge on search results

## Not Included

### `api_transcribe.py` (from ABS project)
The existing enqueue endpoints handle all episode types:
- `POST /api/episodes/{id}/process`
- `POST /api/episodes/process-batch`
- `POST /api/episodes/process-all-pending`

### `api_library.py` (from ABS project)
The existing `api_podcasts.py` handles CRUD for all library items including ABS-sourced ones.

### `feedparser` dependency
Already present in the podcast project.

## Key Behaviors

| Behavior | RSS | ABS |
|----------|-----|-----|
| Discovery | RSS feed polling every 6h | ABS API polling every 6h |
| New item creation | Auto-create Podcast rows via RSS poller | Auto-create Podcast rows via ABS poller |
| Episode auto-enqueue | Only if `auto_process == True` | Only if `auto_process == True` |
| Manual enqueue | Via existing endpoints | Via existing endpoints |
| E-books | N/A | Shown in dashboard, marked "not transcribable", skipped by poller |
| Media type | Always NULL (RSS) | Set to `"podcast"`, `"book"`, or `"ebook"` |

## Migration

No data migration from the old ABS project. Start fresh:
1. Keep existing podcast data in current database
2. Add new columns via Alembic migration (all nullable)
3. ABS items will be discovered and added fresh via polling
4. Old ABS project database is not touched

## Port References

The ABS project is located at `/home/ksn/git-ksn/audiobookshelf-transcribe-and-search`. Key files to port from:
- `app/adapters/abs.py` → `app/adapters/abs.py`
- `app/services/abs_poller.py` → `app/services/abs_poller.py`
- `app/routers/api_abs.py` → `app/routers/api_abs.py`
- `app/templates/library_detail.html` → `app/templates/library_detail.html`
