# Portal Episodes Tab — Design Spec

**Date:** 2026-06-15
**Status:** Approved

## Problem

Portal brugere kan søge og se insights, men har ingen måde at browse eller læse alle transkriberede episoder uden at kende deres titel på forhånd. Portalen mangler en arkiv-/biblioteksvisning.

## Goal

Tilføj en tredje tab "Episodes" på portal-forsiden, der viser en flad kronologisk liste over alle transkriberede episoder tilknyttet portalen, med direkte adgang til at læse fulde transcripts.

## Out of Scope

- Filtrering og sortering i UI (ingen dropdown for podcast, dato-range, osv.)
- Cover-billeder per episode (episodes har ingen `cover_url` i modellen)
- Ny portal-specific route — eksisterende `/episodes/{id}` + `portal_episode.html` genbruges
- Ny template-fil — episodekort og "load more" lever i `portal_home.html`

## Architecture

### Ændring 1: `GET /api/episodes` udvides

**Fil:** `app/routers/api_episodes.py`

Tilføjer `podcast_ids: Optional[str] = None` query-param (komma-separerede UUIDs). Mønsteret er identisk med search og insights-endpointsne.

Når `podcast_ids` er angivet:
- Filtreres til episoder hvis `podcast_id` er i listen
- JOINes med `podcasts`-tabellen for at hente `podcast_title`
- Returneres kun episoder med `status = "done"`
- Sorteres `published_at DESC` (nyeste først)
- Pagineres via eksisterende `limit`/`offset` params (default limit: 50)

Eksisterende `podcast_id` (singular) param bevares uændret for bagudkompatibilitet.

**Nyt felt i responset** (kun når `podcast_ids` bruges, ellers `null`):
```json
{ "podcast_title": "Min Podcast" }
```

Skemaet udvides med `podcast_title: Optional[str]`.

### Ændring 2: `portal_home.html` — ny Episodes-tab

**Fil:** `app/templates/portal_home.html`

**Tab-knap:** Tilføjes ved siden af "Search" og "Insights" i tab-baren.

**Alpine.js state** (tilføjet til eksisterende `data()`):
```js
episodes: [],
episodesLoaded: false,
episodesOffset: 0,
episodesHasMore: false,
episodesLoading: false,
```

**`loadEpisodes()` metode:**
- Kaldes første gang tab aktiveres (lazy load)
- `GET /api/episodes?podcast_ids=<portal_podcast_ids>&status=done&limit=50&offset=<episodesOffset>`
- Appender til `episodes` array
- Opdaterer `episodesOffset` og `episodesHasMore`
- Sætter `episodesLoaded = true` efter første kald

**Episode-kort viser:**
| Felt | Kilde |
|------|-------|
| Titel | `episode.title` — link til `/episodes/{id}` |
| Podcast-navn | `episode.podcast_title` |
| Udgivelsesdato | `episode.published_at` — formateret som lokal dato |
| Varighed | `episode.duration_seconds` — formateret som "1t 23m" (eller "45m") |
| Summary-uddrag | `episode.transcript.summary` første ~150 tegn, kun hvis tilgængeligt |

**"Load more"-knap** vises hvis `episodesHasMore`. Kalder `loadEpisodes()` og appender.

**Tab-skift:** Når `tab` sættes til `'episodes'` og `!episodesLoaded`, kaldes `loadEpisodes()` automatisk via Alpine.js `$watch` eller `x-init`-svarende logik.

## Data Flow

```
portal_home.html JS
  → "Episodes" tab klikket
  → loadEpisodes() kaldt (første gang)
  → GET /api/episodes?podcast_ids=id1,id2&status=done&limit=50&offset=0
  → api_episodes.py: SELECT episodes JOIN podcasts WHERE podcast_id IN (id1, id2) AND status='done' ORDER BY published_at DESC
  → JSON liste med podcast_title
  → Episodes array renderes som kort
  → "Load more" → offset += 50 → næste side appended
```

## API Contract

### Request
```
GET /api/episodes?podcast_ids=uuid1,uuid2&status=done&limit=50&offset=0
```

### Response (eksempel)
```json
[
  {
    "id": "...",
    "title": "Episode 42: Om alt det",
    "description": "...",
    "duration_seconds": 3720,
    "published_at": "2026-05-01T08:00:00+00:00",
    "status": "done",
    "podcast_title": "Min Podcast",
    "transcript": {
      "summary": "I denne episode taler vi om..."
    }
  }
]
```

`podcast_title` er `null` når `podcast_ids`-param ikke er angivet (eksisterende kald).

## Tests

- **Unit/integration:** `test_api_episodes.py` (eller tilsvarende) — test at `podcast_ids`-param filtrerer korrekt, returnerer `podcast_title`, kun `status=done`, sorteret `published_at DESC`, paginering fungerer.
- **Eksisterende tests:** Verificer at eksisterende `podcast_id`-param stadig virker uændret.

## Estimated Scope

| Fil | Ændring |
|-----|---------|
| `app/routers/api_episodes.py` | +~20 linjer (podcast_ids param, JOIN, schema-felt) |
| `app/templates/portal_home.html` | +~80 linjer (tab-knap, panel, Alpine.js state+metoder, episodekort) |
| `tests/integration/test_api_episodes.py` | +~40 linjer (nye test-cases) |
