# Queue Page — Joblog for Episode Processing

## Problem

Det er uoverskueligt at følge med i hvad der foregår, når mange episoder
bliver sat i kø til processing. Der er intet samlet overblik på tværs af
podcasts — man må gå ind på hver enkelt podcast-detalje-side for at se
status.

## Løsning

En ny **Queue**-side (`/queue`) der viser alle episoder på tværs af podcasts
grupperet efter status: kørende, i kø, fejlede, og færdige.

## API

### `GET /api/queue`

Returnerer en JSON-struktur med episoder sorteret pr. gruppe.

**Response:**

```json
{
  "items": [
    {
      "id": "uuid",
      "title": "Episode title",
      "podcast_id": "uuid",
      "podcast_title": "Podcast name",
      "status": "new",
      "error_message": null,
      "processing_seconds": null,
      "created_at": "2026-05-23T10:00:00+00:00",
      "updated_at": "2026-05-23T10:00:00+00:00"
    }
  ],
  "counts": {
    "running": 2,
    "queued": 15,
    "error": 1,
    "done": 50
  }
}
```

**Sortering:**
- `running` (downloading, transcribing, summarizing, indexing): updated_at DESC
- `queued` (new): created_at ASC (ældste først i køen)
- `error` (error): updated_at DESC
- `done` (ready): updated_at DESC, max 50

**Query:**
- Joine `Episode` med `Podcast` for at få `podcast_title`.
- Limit 50 for `done` for at undgå at listen bliver uendelig.
- Ingen paginering i første version (kan tilføjes hvis nødvendigt).

## Frontend

### Ny menu: "Queue" → `/queue`

Link i navigationsbaren i `base.html`, ved siden af Dashboard, Search, Admin.

### Template: `queue.html`

Fire sektioner med overskrifter og tællere:

```
┌─────────────────────────────────────────────┐
│  Queue                    (2 running, 15 queued) │
├─────────────────────────────────────────────┤
│  ▶ Running (2)                               │
│  ├── Episode A — Podcast X — downloading…   │
│  └── Episode B — Podcast Y — transcribing…  │
│                                             │
│  ⏳ In Queue (15)                            │
│  ├── Episode C — Podcast Z — 5 min ago      │
│  ├── Episode D — Podcast W — 10 min ago     │
│  └── ...                                    │
│                                             │
│  ✕ Failed (1)                               │
│  └── Episode E — Podcast X — "timeout"      │
│                                             │
│  ✓ Completed (50)                            │
│  ├── Episode F — Podcast Y — 2 hours ago    │
│  └── ...                                    │
└─────────────────────────────────────────────┘
```

**Hver række viser:**
- Episode-titel (link til `/episodes/{id}`)
- Podcast-navn (link til `/podcasts/{id}`)
- Status-badge med farve
- Tid siden oprettet/opdateret
- Ved fejl: error_message
- Ved running: hvilken fase (status-teksten)

**Status-badge farver:**
- `new` → gul "Queued"
- `downloading` / `transcribing` / `summarizing` / `indexing` → grøn med spinner-emoji
- `ready` → grå "Completed"
- `error` → rød "Failed"

**Auto-refresh:**
- Alpine.js `x-data` med `init()` der kalder `setInterval` hver 2. sekund
- Samme mønster som `podcast_detail.html`
- Stopper polling hvis `running === 0 && queued === 0`

## Ingen databaseændringer

Bygger udelukkende på eksisterende `episodes.status`-felt. Ingen nye
tabeller eller kolonner.

## Fremtidige muligheder (ikke i scope)

- Job-log tabel med fase-timing
- Annuller/kø-ompriortering
- Paginering af completed
- Filtrering pr. podcast
