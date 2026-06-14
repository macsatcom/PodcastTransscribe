# SP0 — Safety Net & Quality Gates (Design Spec)

**Date:** 2026-06-14
**Status:** Approved (design)
**Sub-project:** SP0 of the targeted-rebuild roadmap
**Author:** brainstorming session

---

## 1. Context

`podcast-transcription-search` is a ~4,800-line FastAPI + Postgres/pgvector
application that has grown organically. It currently has:

- **No CI quality gates.** The only GitHub Actions workflow (`release.yml`)
  builds and pushes a Docker image on `release: published`. No tests, lint, or
  type checks run on push or PR.
- **~5–10% behavioral test coverage.** Of five test files, two execute no
  application code at all (`test_api_episodes_pagination.py` does AST analysis;
  `test_podcast_detail_loading_controls.py` does string-grep on a template).
- **A dead integration harness.** `tests/conftest.py` defines `test_engine`,
  `db_session`, and `client` fixtures against a real Postgres test DB, but no
  test uses the `client` fixture or queries the real DB meaningfully.
- **A history of migration-induced outages.** Two production-breaking bugs
  shipped via Alembic migrations (the ivfflat 2000-dimension ceiling in 0.18.1;
  a dropped `client.post()` in 0.19.1). Migrations run on startup. None are
  tested.
- **A test-collection isolation bug.** Running the full suite imports
  `app.adapters` from a *sibling* repository on disk, not this project.

SP0 is the foundation for the subsequent rebuild sub-projects (SP1 auth, SP2
portals, SP3 queue, SP4 persistence, SP5 config, SP6 frontend, SP7 backups).
Every later change must ride on this safety net.

## 2. Goal

Establish automated quality gates and a working integration-test harness so
that:

1. No future sub-project ships a regression unguarded.
2. The migration failure mode that broke production twice is caught in CI.
3. The previously-dead DB integration harness is activated and used.

### Success criteria

- A CI workflow runs on every push and pull request and executes lint, type
  check (advisory), and the test suite against a real pgvector Postgres.
- `ruff` passes (blocking) on the whole codebase.
- `mypy` runs and reports (advisory / non-blocking).
- `pytest` runs the activated harness, including at least one integration test
  that exercises the **real Alembic migration path** end-to-end.
- Coverage is measured and reported (no gate).
- The two non-executing "fake" tests are replaced by real equivalents.
- `pytest` reliably collects only this repository's tests.
- The `web` Docker service reports health.

## 3. Scope

### In scope

- GitHub Actions CI workflow (`ci.yml`) on `push` + `pull_request`.
- `ruff` (blocking), `mypy` (advisory), `pytest-cov` (report-only).
- Fix test-collection isolation so only this repo's `app` package loads.
- Activate `conftest.py` using **Alembic-migrated** test databases.
- A thin, high-value integration test layer:
  1. Migration boot path.
  2. One FTS search end-to-end.
  3. One semantic/RAG path (mock only the OpenRouter HTTP boundary).
  4. Real-DB episode-list pagination (replacing the AST stand-in).
- Retire the two fake tests.
- Pre-commit hooks (`ruff` lint + format).
- `web` service healthcheck in `docker-compose.yml` + a `GET /healthz`
  liveness endpoint if one does not already exist.
- Structured logging baseline (consistent format, `LOG_LEVEL` env override),
  no behavior change.

### Out of scope (deferred to later sub-projects)

- Broad endpoint/service test coverage (rides with each sub-project).
- `mypy` in blocking mode (later phase, after types are cleaned up).
- Coverage gating / `--cov-fail-under` (later phase, once a baseline exists).
- Authentication (SP1).
- Any app behavior change beyond logging format and the healthcheck endpoint.
- Resolving the `create_all` + Alembic duality in `app/main.py` (SP4). SP0's
  **test harness** uses migrations as the schema authority, which pre-stages
  that direction, but SP0 does not modify the application startup sequence.

## 4. Key Design Decisions

| # | Decision | Choice | Rationale |
|---|----------|--------|-----------|
| D1 | CI test DB | `pgvector/pgvector:pg16` service container | Same image as production; the schema uses `Vector(3072)`; stock postgres lacks pgvector. |
| D2 | Lint/type strictness | `ruff` blocking, `mypy` advisory | A strict mypy pass on a large, never-type-checked codebase would block all progress on day one. Ruff is fast and mostly auto-fixable. |
| D3 | Coverage | Measure + report, no gate | A hard floor now would be meaningless or obstructive while the suite is small. Visibility now; ratchet later. |
| D4 | New-test scope | Thin high-value smoke layer | Proves the harness end-to-end and guards the migration failure mode without turning SP0 into a multi-week test marathon. |
| D5 | Pre-commit | Yes (`ruff`) | Tightens the local feedback loop before CI. |
| D6 | Test-collection isolation | Fix in SP0 | A safety net that can't reliably collect its own tests is not a safety net. |
| D7 | Test schema source | `alembic upgrade head` on a clean DB (not `create_all`) | Directly exercises the real migration path that caused both prior outages; surfaces model↔migration drift as a visible signal. |

## 5. Components & File Changes

### New files

- **`.github/workflows/ci.yml`** — runs on `push` + `pull_request`. Single job:
  - Checkout
  - Set up Python 3.12
  - `pgvector/pgvector:pg16` service container (health-gated) exposing the test DB
  - Install `.[dev]` plus `ruff`, `mypy`, `pytest-cov`
  - `ruff check` (blocking)
  - `ruff format --check` (blocking)
  - `mypy app` (advisory; `continue-on-error: true`)
  - `pytest --cov=app --cov-report=term-missing` (blocking) against the service
    container, with `DATABASE_URL` pointed at it
- **`.pre-commit-config.yaml`** — `ruff` lint + `ruff format` hooks.
- **`tests/integration/test_migrations.py`** — fresh DB → `alembic upgrade head`
  → assert all tables and the three Alembic-only indexes exist:
  `ix_episodes_podcast_published`, `ix_transcripts_fts_simple`,
  `ix_chunks_embedding_3072`.
- **`tests/integration/test_search_api.py`** — seed a transcript + chunk; exercise
  one FTS path and one semantic/RAG path; mock only the OpenRouter HTTP boundary.
- **`tests/integration/test_episodes_api.py`** — real-DB pagination test
  (limit / offset / ordering) replacing the AST stand-in.

### Modified files

- **`pyproject.toml`** — add `[tool.ruff]`, `[tool.mypy]`; extend
  `[tool.pytest.ini_options]` with `testpaths`; add dev deps `ruff`, `mypy`,
  `pytest-cov`. No new runtime deps.
- **`tests/conftest.py`** — switch the session fixture from `create_all` to
  `alembic upgrade head`; ensure per-test transactional rollback; fix package /
  `sys.path` resolution so only this repo's tests collect.
- **`docker-compose.yml`** — add a `healthcheck` to the `web` service.
- **`app/main.py`** (or a small `app/logging_config.py`) — structured logging
  baseline; consistent format; `LOG_LEVEL` env override. No behavior change.
- **`app/routers/`** (if needed) — a minimal `GET /healthz` returning
  `{"status": "ok"}` (liveness only, no DB hit) if no equivalent exists.

### Deleted files

- **`tests/test_api_episodes_pagination.py`** (AST fake) — replaced by
  `tests/integration/test_episodes_api.py`.
- **`tests/test_podcast_detail_loading_controls.py`** (string-grep fake) — the
  stop/resume loading behavior it asserted is UI/JS; its intent is noted for a
  future frontend test approach in SP6, not preserved as a string-grep.

## 6. Test Harness Mechanics

### Database lifecycle

- **Session-scoped** fixture: connect to the test DB (`..._test`), drop all
  objects, run `alembic upgrade head` against it (D7), yield the engine, drop at
  teardown.
- The migration run uses the **test** `DATABASE_URL`. `alembic/env.py` already
  reads `settings.database_url`; the fixture sets that environment value before
  invoking `command.upgrade(...)` so migrations target the test DB, not the dev
  DB.
- **Function-scoped** `db_session`: wrap each test in a transaction, roll back
  after — fast isolation, no cross-test bleed.
- **`client`** fixture: override `get_db` to use the test session. This is the
  fixture that finally gets exercised.

### Mocking boundary

Integration tests mock **only** the outbound HTTP to OpenRouter (via
`pytest-httpx` or by patching `OpenRouterClient._post` / `embed`). pgvector,
FTS, and the real query/aggregation logic execute against real Postgres. The
database is never mocked.

### Test-collection isolation

The earlier full-suite run imported `app.adapters` from a sibling repo on disk.
SP0 pins collection to this repository:

- Set `testpaths` in `[tool.pytest.ini_options]`.
- Ensure the project root resolves first (correct editable/`pip install -e .`
  in CI; appropriate `conftest.py` location / `rootdir`).
- Result: `pytest` only ever loads this project's `app` package.

## 7. Structured Logging Baseline

Today `app/main.py` calls a bare `logging.basicConfig(level=INFO, format=...)`.
SP0 standardizes this in one place:

- Consistent format: timestamp, level, logger name, message.
- INFO default, overridable via `LOG_LEVEL` env var.
- **No** JSON logging, **no** log shipping (YAGNI at this scale).
- No behavior change — purely format/level consolidation.

## 8. Healthcheck

- Add a `docker-compose.yml` `healthcheck` to `web`, mirroring how `db` already
  reports health.
- The check hits a lightweight liveness endpoint. If `GET /healthz` does not
  already exist, SP0 adds a trivial one returning `{"status": "ok"}` (no DB
  hit). This sets up future readiness/`depends_on` use without coupling
  liveness to DB availability.

## 9. Error Handling & Edge Cases

- **CI DB not ready:** the workflow gates `pytest` on the service container's
  health (Postgres `pg_isready` / service health) before running tests.
- **Migration failure in CI:** a failing `alembic upgrade head` fails the
  migration test (and thus the job) — this is the desired behavior (it is the
  exact failure mode SP0 exists to catch).
- **mypy errors:** reported but non-blocking (`continue-on-error`) — they do not
  fail the build in SP0.
- **Flaky external calls:** integration tests never call OpenRouter for real;
  the HTTP boundary is always mocked, so tests are deterministic and offline.
- **Local vs CI DB URL:** both resolve through `DATABASE_URL`; CI points it at
  the service container, local points at the developer's `..._test` DB.

## 10. Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| HNSW index build in `0002` is slow / version-sensitive | The migration already wraps it in a `DO/EXCEPTION` block; the test asserts table+index presence but tolerates the documented graceful-degradation path. (Index-presence assertion will be written to match the migration's actual guarantees.) |
| `create_all` vs Alembic duality confuses the harness | SP0 harness uses migrations only; it does not touch app startup. Duality resolution is SP4. |
| Ruff surfaces a large number of lint findings | Most are auto-fixable (`ruff check --fix`, `ruff format`); the initial cleanup is part of SP0's implementation. |
| Test-collection fix interacts with the sibling repo on the dev machine | Pin `testpaths` + `rootdir`; verify locally that only this repo collects. |

## 11. Deliverables Checklist

- [ ] `.github/workflows/ci.yml` (push + PR; lint blocking, mypy advisory, tests blocking, coverage reported)
- [ ] `.pre-commit-config.yaml` (ruff lint + format)
- [ ] `pyproject.toml` updated (`[tool.ruff]`, `[tool.mypy]`, `testpaths`, dev deps)
- [ ] `tests/conftest.py` migrated to Alembic-based schema + isolation fix
- [ ] `tests/integration/test_migrations.py`
- [ ] `tests/integration/test_search_api.py`
- [ ] `tests/integration/test_episodes_api.py`
- [ ] Two fake tests deleted
- [ ] `docker-compose.yml` `web` healthcheck + `GET /healthz` (if absent)
- [ ] Structured logging baseline
- [ ] Whole suite green locally and in CI

## 12. Definition of Done

- CI is green on a PR: ruff passes, mypy reports (advisory), all tests pass
  against the pgvector service container, coverage printed.
- The migration integration test fails if a migration is broken (verified by a
  temporary deliberate break during development, then reverted).
- `pytest` run locally collects only this repo's tests.
- `docker compose ps` shows `web` as healthy.
