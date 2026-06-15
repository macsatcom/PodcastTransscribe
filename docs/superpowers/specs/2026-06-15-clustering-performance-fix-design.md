# Clustering Performance & Safety Fix — Design Spec

**Date:** 2026-06-15
**Status:** Approved

## Problem

"Refresh Topics" på Insights-siden kører i timevis med ~100% CPU på én kerne, blokerer hele web-containeren, og efterlader processen i en tilsyneladende vedvarende høj-CPU tilstand. Diagnose via `py-spy` viste at `MainThread` stod i `run_clustering → HDBSCAN.fit_predict → _hdbscan_prims → kneighbors`.

## Root Cause (bekræftet med målinger)

To separate fejl:

1. **Primær — algoritmevalg:** `app/services/clustering.py:102` kalder `HDBSCAN(min_cluster_size=..., metric="euclidean")` uden `algorithm`. Default `algorithm="auto"` bygger et KD/ball-tree, som kollapser ved 3072-dimensionelle embeddings (curse of dimensionality). Målt på 3072-dim vektorer:
   - n=2000, `algorithm="auto"`: **>10 min, ikke færdig**
   - n=2000, `algorithm="brute"`: **0,5 s**
   - n=5000, brute: 2,2 s
   - n=10000, brute: 8,3 s

2. **Sekundær — synkron kørsel på event-loopen:** `run_clustering()` er `async`, men `np.stack` + `HDBSCAN.fit_predict` er tung synkron CPU-arbejde der kører direkte på asyncio event-loopen. Endpointet `POST /api/insights/clusters/refresh` (`api_insights.py:160`) `await`er hele kørslen, så HTTP-requesten hænger i hele beregningstiden. Der er ingen guard mod samtidige kørsler → manuel knap + natligt job + retries kan stacke.

## Goal

1. Gør clustering hurtig (sekunder, ikke timer) ved at sætte `algorithm="brute"`.
2. Flyt CPU-arbejdet væk fra event-loopen, så web-appen ikke blokeres.
3. Forhindr samtidige/stacked kørsler med en guard.
4. Gør "Refresh Topics"-endpointet fire-and-forget (returnér straks).
5. Bevar både manuel knap OG det natlige `daily_clustering`-job — begge guard-beskyttede.

## Out of Scope

- Ingen hård sampling / øvre grænse på antal chunks (brute gør det unødvendigt ved realistiske størrelser; tages som separat opgave hvis arkivet vokser ekstremt).
- Ingen ændring af clustering-output/semantik (samme topics, samme representative chunks, samme episode-assignments).
- Ingen ændring af `daily_clustering`-skemaet (kl. 03:00 bevares).
- Ingen multiprocessing/`n_jobs` (målt langsommere pga. overhead; brute er BLAS-vektoriseret).

## Architecture

### Ændring 1: Algoritme + ikke-blokerende compute (`app/services/clustering.py`)

Split `run_clustering()` så den tunge synkrone del isoleres og køres i en tråd:

- Behold async data-load (SQLAlchemy) og async persist (DB writes) på event-loopen.
- Udtræk den rene CPU-del — normalisering, `np.stack`, `HDBSCAN.fit_predict`, og udregning af labels/centroids/representatives-indices — i en separat **synkron** funktion `compute_clusters(matrix, ...)`.
- Kald denne via `await asyncio.to_thread(compute_clusters, ...)`.
- `HDBSCAN` instantieres med `algorithm="brute"` og `copy=True` (sidstnævnte fjerner FutureWarning og undgår in-place mutation af matrix).

`_generate_label` (OpenRouter-kald) forbliver async og kaldes fra event-loopen efter compute (den laver netværks-I/O, ikke CPU).

### Ændring 2: Concurrency-guard (`app/services/clustering.py`)

Modul-niveau guard:

```python
_clustering_lock = asyncio.Lock()

def is_clustering_running() -> bool:
    return _clustering_lock.locked()
```

`run_clustering()` wrappes så den ikke-blokerende erhverver låsen; hvis allerede låst, returnerer den straks uden at køre (og logger "skipped, already running"). Dette beskytter både manuel og natlig kørsel.

### Ændring 3: Fire-and-forget endpoint (`app/routers/api_insights.py`)

`refresh_clusters()` ændres til:
- Hvis `is_clustering_running()`: returnér `{"status": "already_running"}` straks.
- Ellers: start kørslen som baggrundstask (`asyncio.create_task(run_clustering())`) og returnér `{"status": "started"}` straks.

Dette fjerner den fleretimers hængende request og dermed nginx/browser-timeout/retry-stacking.

## Data Flow (efter fix)

```
POST /api/insights/clusters/refresh
  → is_clustering_running()? → ja: {"status":"already_running"} (straks)
  → nej: asyncio.create_task(run_clustering()); {"status":"started"} (straks)

run_clustering()  (baggrundstask)
  → acquire _clustering_lock (skip hvis låst)
  → async: load chunks fra DB
  → await asyncio.to_thread(compute_clusters, matrix, ...)   # HDBSCAN brute, ikke på loopen
  → async: _generate_label(...) per cluster (OpenRouter)
  → async: wipe gamle auto-topics + persist nye
  → release lock
```

## Contract

`POST /api/insights/clusters/refresh` returnerer nu:
- `{"status": "started"}` — kørsel sat i gang
- `{"status": "already_running"}` — en kørsel er allerede i gang

(Tidligere returnerede den `{"status": "clustering started"}` efter at have ventet på hele kørslen.)

Frontend (`search.html:433` `refreshClusters()`) kræver ingen ændring: den fyrer POST'en og kalder `loadTopics()` efter 5s uafhængigt. Resultatet dukker op når kørslen er færdig (sekunder nu).

## Testing

Nye tests i `tests/integration/test_clustering.py`:

1. **`algorithm="brute"` bruges** — patch/inspicér at HDBSCAN konstrueres med `algorithm="brute"` (unit-niveau på `compute_clusters`), så regressionen ikke kan snige sig tilbage.
2. **Guard afviser samtidig kørsel** — når låsen er taget, returnerer `run_clustering()` straks uden at køre compute (verificér via at compute ikke kaldes / hurtig retur).
3. **Endpoint fire-and-forget** — `POST /clusters/refresh` returnerer `{"status":"started"}` uden at vente; ved aktiv kørsel returnerer `{"status":"already_running"}`.
4. **Output uændret (smoke)** — på et lille syntetisk datasæt producerer `run_clustering()` ≥1 topic og EpisodeTopic-rækker (sikrer refactor ikke brød persisteringen).

## Estimated Scope

| Fil | Ændring |
|-----|---------|
| `app/services/clustering.py` | Split compute-del ud, `asyncio.to_thread`, `algorithm="brute"`, guard-lock (~50-70 linjer ændret) |
| `app/routers/api_insights.py` | fire-and-forget endpoint (~8 linjer) |
| `tests/integration/test_clustering.py` | nye tests (~120 linjer) |

## Operational Note

Akut afhjælpning på produktion (uafhængigt af kodefix): `docker compose restart web` dræber den nuværende hængende kørsel. Efter deploy af fixet vil fremtidige kørsler tage sekunder.
