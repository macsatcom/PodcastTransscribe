# Optional Auth (SP1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional, admin-configurable username/password login — one user for the main system and one separate user per portal — with auth OFF by default.

**Architecture:** App-level login using a signed session cookie (`itsdangerous`) and bcrypt password hashes (`passlib`) stored in the database. A FastAPI HTTP middleware guards the main app and each portal app; a `scope` claim inside the signed token isolates main sessions from portal sessions. Main credentials live in the `settings` key/value table; portal credentials live as new columns on the `portals` table.

**Tech Stack:** FastAPI, SQLAlchemy 2 (async), Alembic, Jinja2, Alpine.js, `passlib[bcrypt]`, `itsdangerous`, pytest + pytest-asyncio + httpx.

---

## Design reference

Spec: `docs/superpowers/specs/2026-06-14-optional-auth-design.md`

## Conventions used by this codebase (read before starting)

- Settings are rows in the `settings` table (`app/models/setting.py`, `Setting(key, value)`), read via `await session.get(Setting, "<key>")`.
- The main app builds `app = FastAPI(...)` in `app/main.py` and includes routers at the bottom.
- Portals run as **separate uvicorn processes** via `app/portal_manager.py`, served by the factory `app/portal_server.py:create_app()`. `PORTAL_ID` is passed via env.
- Migrations live in `alembic/versions/NNNN_*.py`. Current head is `0003_episode_perf_indexes`. **The next migration is `0004_portal_auth`** (note: `0003` is already taken by the perf-index migration; do not reuse it). Migrations use idempotent SQL (`ADD COLUMN IF NOT EXISTS`).
- Tests use a real Postgres+pgvector test DB. `tests/conftest.py` provides an async `client` fixture (httpx ASGITransport against `app`) and a `db_session` fixture. Integration tests live in `tests/integration/`.
- Run tooling with `uv` (the repo standard). If `uv` is unavailable use `pytest`/`ruff` directly; commands below show `uv run` form.

## File Structure

**Create:**
- `app/auth.py` — pure auth helpers (hashing, token sign/verify, secret accessor, constants, cached main-auth state accessor + invalidation).
- `app/routers/auth_ui.py` — main app `/login` (GET/POST) and `/logout` (POST) routes.
- `app/templates/login.html` — standalone login page (no nav chrome), reused by main and portals.
- `alembic/versions/0004_portal_auth.py` — adds `auth_enabled`, `auth_username`, `auth_password_hash` to `portals`.
- `tests/test_auth_unit.py` — unit tests for hashing + token helpers.
- `tests/integration/test_auth_main.py` — main login/middleware integration tests.
- `tests/integration/test_auth_portal.py` — portal auth-field persistence + scope-isolation tests.

**Modify:**
- `pyproject.toml` — add `passlib[bcrypt]`, `itsdangerous` deps.
- `app/models/portal.py` — add three auth columns.
- `app/routers/api_settings.py` — add `GET`/`PUT /api/settings/auth`; keep `auth_*` out of `VALID_KEYS`.
- `app/routers/api_portals.py` — accept/persist/return portal auth fields (never the hash/raw password).
- `app/main.py` — register `auth_ui` router + add main auth middleware.
- `app/portal_server.py` — add portal auth middleware + `/login` + `/logout`.
- `app/routers/ui.py` — pass `main_auth_enabled` into template context (for nav logout button).
- `app/templates/base.html` — conditional Logout form in nav.
- `app/templates/admin.html` — Authentication card (main) + portal-form auth fields + lock badge.

---

## Task 1: Add dependencies

**Files:**
- Modify: `pyproject.toml:5-19`

- [ ] **Step 1: Add the two runtime dependencies**

Edit the `dependencies` array in `pyproject.toml` to add `passlib[bcrypt]` and `itsdangerous` (keep alphabetical-ish grouping consistent with existing style):

```toml
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg",
    "alembic",
    "apscheduler>=3.10",
    "httpx",
    "feedparser",
    "jinja2",
    "python-multipart",
    "pgvector",
    "pydantic-settings",
    "scikit-learn>=1.3",
    "passlib[bcrypt]",
    "itsdangerous",
]
```

- [ ] **Step 2: Sync the environment**

Run: `uv sync --extra dev`
Expected: resolves and installs `passlib`, `bcrypt`, `itsdangerous` with no errors.

- [ ] **Step 3: Verify imports work**

Run: `uv run python -c "import passlib.hash, itsdangerous; print('ok')"`
Expected: prints `ok`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "build(auth): add passlib[bcrypt] and itsdangerous deps"
```

(If `uv.lock` is not tracked in this repo, just `git add pyproject.toml`.)

---

## Task 2: Auth helper module (hashing + tokens)

**Files:**
- Create: `app/auth.py`
- Test: `tests/test_auth_unit.py`

- [ ] **Step 1: Write the failing unit test**

Create `tests/test_auth_unit.py`:

```python
from app.auth import (
    hash_password,
    verify_password,
    sign_token,
    verify_token,
)


def test_hash_and_verify_password_roundtrip():
    hashed = hash_password("s3cret")
    assert hashed != "s3cret"
    assert verify_password("s3cret", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_sign_and_verify_token_roundtrip():
    secret = "test-secret-value"
    token = sign_token(secret, {"scope": "main"})
    assert isinstance(token, str)
    assert verify_token(secret, token) == {"scope": "main"}


def test_verify_token_rejects_tampered_token():
    secret = "test-secret-value"
    token = sign_token(secret, {"scope": "main"})
    tampered = token + "x"
    assert verify_token(secret, tampered) is None


def test_verify_token_rejects_wrong_secret():
    token = sign_token("secret-a", {"scope": "main"})
    assert verify_token("secret-b", token) is None


def test_verify_token_handles_garbage():
    assert verify_token("secret", "not-a-real-token") is None
    assert verify_token("secret", "") is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_auth_unit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.auth'` (or import error).

- [ ] **Step 3: Create the helper module**

Create `app/auth.py`:

```python
"""Authentication helpers: password hashing and signed session tokens.

Pure functions with no FastAPI coupling. Used by both the main app
(``app/main.py`` + ``app/routers/auth_ui.py``) and each portal app
(``app/portal_server.py``).
"""

from __future__ import annotations

import secrets

from itsdangerous import BadSignature, URLSafeSerializer
from passlib.hash import bcrypt

# Shared cookie name across main + portal apps. The signed token's ``scope``
# (and ``id`` for portals) is what actually isolates sessions.
SESSION_COOKIE = "pts_session"

# Paths every protected app must always serve without auth.
PUBLIC_PATHS = {"/healthz", "/login", "/logout"}
PUBLIC_PREFIXES = ("/static",)

_TOKEN_SALT = "pts-auth"

# Settings keys (main scope).
AUTH_MAIN_ENABLED = "auth_main_enabled"
AUTH_MAIN_USERNAME = "auth_main_username"
AUTH_MAIN_PASSWORD_HASH = "auth_main_password_hash"
AUTH_SESSION_SECRET = "auth_session_secret"


def hash_password(plain: str) -> str:
    """Return a bcrypt hash for ``plain``."""
    return bcrypt.hash(plain)


def verify_password(plain: str, hashed: str | None) -> bool:
    """Return True if ``plain`` matches ``hashed``. False on any error/empty."""
    if not hashed:
        return False
    try:
        return bcrypt.verify(plain, hashed)
    except (ValueError, TypeError):
        return False


def sign_token(secret: str, payload: dict) -> str:
    """Sign a small JSON-serializable payload into a URL-safe token."""
    serializer = URLSafeSerializer(secret, salt=_TOKEN_SALT)
    return serializer.dumps(payload)


def verify_token(secret: str, token: str | None) -> dict | None:
    """Return the payload if the token is valid, else None (never raises)."""
    if not token:
        return None
    serializer = URLSafeSerializer(secret, salt=_TOKEN_SALT)
    try:
        data = serializer.loads(token)
    except (BadSignature, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def generate_secret() -> str:
    """Generate a fresh random secret for cookie signing."""
    return secrets.token_urlsafe(32)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_auth_unit.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add app/auth.py tests/test_auth_unit.py
git commit -m "feat(auth): add password hashing and signed-token helpers"
```

---

## Task 3: Session-secret accessor + cached main-auth state

**Files:**
- Modify: `app/auth.py`
- Test: `tests/integration/test_auth_main.py` (new file, first test only here)

This adds DB-backed helpers: a persistent shared signing secret, and a short-TTL cache of main-auth state to avoid a DB hit per request.

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_auth_main.py`:

```python
import pytest

from app import auth


@pytest.mark.asyncio
async def test_get_session_secret_persists(db_session):
    secret1 = await auth.get_session_secret(db_session)
    assert isinstance(secret1, str) and len(secret1) >= 16
    # Second call returns the same persisted value.
    secret2 = await auth.get_session_secret(db_session)
    assert secret1 == secret2


@pytest.mark.asyncio
async def test_main_auth_state_defaults_disabled(db_session):
    auth.invalidate_main_auth_cache()
    state = await auth.load_main_auth_state(db_session)
    assert state.enabled is False
    assert state.username == ""
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/integration/test_auth_main.py -v`
Expected: FAIL — `AttributeError: module 'app.auth' has no attribute 'get_session_secret'`.

- [ ] **Step 3: Add the accessors to `app/auth.py`**

Append to `app/auth.py`:

```python
import time
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.setting import Setting


async def get_session_secret(session: AsyncSession) -> str:
    """Read the shared cookie-signing secret, generating+persisting if absent."""
    row = await session.get(Setting, AUTH_SESSION_SECRET)
    if row and row.value:
        return row.value
    new_secret = generate_secret()
    if row:
        row.value = new_secret
    else:
        session.add(Setting(key=AUTH_SESSION_SECRET, value=new_secret))
    await session.commit()
    return new_secret


@dataclass
class MainAuthState:
    enabled: bool
    username: str
    password_hash: str
    secret: str


_main_auth_cache: dict = {"state": None, "expires": 0.0}
_MAIN_AUTH_TTL = 5.0


def invalidate_main_auth_cache() -> None:
    """Force the next load_main_auth_state() to hit the DB."""
    _main_auth_cache["state"] = None
    _main_auth_cache["expires"] = 0.0


async def load_main_auth_state(session: AsyncSession) -> MainAuthState:
    """Return cached main-auth config (≈5s TTL)."""
    now = time.monotonic()
    cached = _main_auth_cache["state"]
    if cached is not None and now < _main_auth_cache["expires"]:
        return cached

    enabled_row = await session.get(Setting, AUTH_MAIN_ENABLED)
    user_row = await session.get(Setting, AUTH_MAIN_USERNAME)
    hash_row = await session.get(Setting, AUTH_MAIN_PASSWORD_HASH)
    secret = await get_session_secret(session)

    state = MainAuthState(
        enabled=bool(enabled_row and enabled_row.value == "1"),
        username=(user_row.value if user_row else "") or "",
        password_hash=(hash_row.value if hash_row else "") or "",
        secret=secret,
    )
    _main_auth_cache["state"] = state
    _main_auth_cache["expires"] = now + _MAIN_AUTH_TTL
    return state
```

Note: move the `import time` / `from dataclasses import dataclass` / SQLAlchemy + `Setting` imports to the top of the file with the other imports if you prefer; functionally either is fine since this is one module.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/integration/test_auth_main.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add app/auth.py tests/integration/test_auth_main.py
git commit -m "feat(auth): add session-secret accessor and cached main-auth state"
```

---

## Task 4: Main login routes (`/login`, `/logout`)

**Files:**
- Create: `app/routers/auth_ui.py`
- Create: `app/templates/login.html`
- Modify: `app/main.py:19-30` (imports), `app/main.py:202-211` (router includes)

- [ ] **Step 1: Create the login template**

Create `app/templates/login.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{{ title }} — Sign in</title>
  <style>
    *,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
    body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
      background:#121212;color:#fff;min-height:100vh;display:flex;
      align-items:center;justify-content:center;padding:24px;}
    .card{background:#181818;border:1px solid rgba(255,255,255,0.08);
      border-radius:12px;padding:32px;width:100%;max-width:360px;}
    h1{font-size:1.25rem;font-weight:700;margin-bottom:4px;}
    .sub{color:#b3b3b3;font-size:0.85rem;margin-bottom:20px;}
    label{display:block;font-size:0.75rem;color:#b3b3b3;margin:12px 0 4px;}
    input{width:100%;background:#1f1f1f;border:1px solid rgba(255,255,255,0.12);
      border-radius:6px;padding:10px 12px;color:#fff;font-size:0.9rem;}
    input:focus{outline:none;border-color:#1ed760;}
    button{width:100%;margin-top:20px;background:#1ed760;color:#000;border:none;
      border-radius:500px;padding:11px;font-weight:600;font-size:0.9rem;cursor:pointer;}
    button:hover{background:#1fdf64;}
    .err{color:#f3727f;font-size:0.8rem;margin-top:12px;min-height:1em;}
  </style>
</head>
<body>
  <form class="card" method="post" action="/login">
    <h1>{{ title }}</h1>
    <div class="sub">Sign in to continue</div>
    <input type="hidden" name="next" value="{{ next_path }}">
    <label for="username">Username</label>
    <input id="username" name="username" autocomplete="username" autofocus>
    <label for="password">Password</label>
    <input id="password" name="password" type="password" autocomplete="current-password">
    <button type="submit">Sign in</button>
    {% if error %}<div class="err">{{ error }}</div>{% endif %}
  </form>
</body>
</html>
```

- [ ] **Step 2: Write the failing integration test (append to `tests/integration/test_auth_main.py`)**

Add these tests:

```python
@pytest.mark.asyncio
async def test_login_page_renders(client):
    resp = await client.get("/login")
    assert resp.status_code == 200
    assert "Sign in" in resp.text


@pytest.mark.asyncio
async def test_login_rejects_when_no_main_credentials(client, db_session):
    # No credentials configured yet -> any login attempt fails (401).
    auth.invalidate_main_auth_cache()
    resp = await client.post(
        "/login",
        data={"username": "x", "password": "y"},
    )
    assert resp.status_code == 401
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/integration/test_auth_main.py -k login -v`
Expected: FAIL — `/login` returns 404 (route not registered yet).

- [ ] **Step 4: Create the router**

Create `app/routers/auth_ui.py`:

```python
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app import auth
from app.database import get_db

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

MAIN_TITLE = "Transcribe Admin"


def _safe_next(next_path: str | None) -> str:
    """Only allow local absolute paths, never open redirects."""
    if next_path and next_path.startswith("/") and not next_path.startswith("//"):
        return next_path
    return "/"


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/"):
    return templates.TemplateResponse(
        request,
        "login.html",
        {"title": MAIN_TITLE, "next_path": _safe_next(next), "error": None},
    )


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    next: str = Form("/"),
    db: AsyncSession = Depends(get_db),
):
    auth.invalidate_main_auth_cache()
    state = await auth.load_main_auth_state(db)
    ok = (
        username == state.username
        and auth.verify_password(password, state.password_hash)
    )
    if not ok:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "title": MAIN_TITLE,
                "next_path": _safe_next(next),
                "error": "Invalid username or password.",
            },
            status_code=401,
        )
    token = auth.sign_token(state.secret, {"scope": "main"})
    resp = RedirectResponse(_safe_next(next), status_code=303)
    resp.set_cookie(
        auth.SESSION_COOKIE, token,
        httponly=True, samesite="lax", path="/",
    )
    return resp


@router.post("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(auth.SESSION_COOKIE, path="/")
    return resp
```

- [ ] **Step 5: Register the router in `app/main.py`**

Add `auth_ui` to the router import block (`app/main.py:19-30`):

```python
from app.routers import (
    api_abs,
    api_episodes,
    api_insights,
    api_podcasts,
    api_portals,
    api_queue,
    api_search,
    api_settings,
    auth_ui,
    health,
    ui,
)
```

And add the include near the other `app.include_router(...)` calls (after `app.include_router(health.router)` at `app/main.py:211`):

```python
app.include_router(auth_ui.router)
```

- [ ] **Step 6: Run to verify passing**

Run: `uv run pytest tests/integration/test_auth_main.py -k login -v`
Expected: PASS (both login tests).

- [ ] **Step 7: Commit**

```bash
git add app/routers/auth_ui.py app/templates/login.html app/main.py tests/integration/test_auth_main.py
git commit -m "feat(auth): add main /login and /logout routes"
```

---

## Task 5: Main settings API for auth (`GET`/`PUT /api/settings/auth`)

**Files:**
- Modify: `app/routers/api_settings.py:1-10` (imports), add endpoints anywhere in the router

- [ ] **Step 1: Write the failing integration test (append to `tests/integration/test_auth_main.py`)**

```python
@pytest.mark.asyncio
async def test_get_auth_settings_defaults(client):
    resp = await client.get("/api/settings/auth")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["username"] == ""


@pytest.mark.asyncio
async def test_put_auth_enable_requires_credentials(client):
    # Enabling without username/password must be rejected.
    resp = await client.put("/api/settings/auth", json={"enabled": True})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_put_auth_sets_credentials_and_never_returns_hash(client):
    resp = await client.put(
        "/api/settings/auth",
        json={"enabled": True, "username": "admin", "password": "hunter2"},
    )
    assert resp.status_code == 200
    # GET reflects enabled + username, never password/hash.
    got = await client.get("/api/settings/auth")
    body = got.json()
    assert body == {"enabled": True, "username": "admin"}
    assert "password" not in body
    assert "password_hash" not in body
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/integration/test_auth_main.py -k auth_settings -v`
Expected: FAIL — `/api/settings/auth` returns 404.

(Note: the `test_put_auth_*` tests share the session-scoped DB; they assert their own writes, so ordering within the file is fine.)

- [ ] **Step 3: Add endpoints to `app/routers/api_settings.py`**

Add imports at the top (after existing imports):

```python
from pydantic import BaseModel

from app import auth
```

Confirm `auth_*` keys are NOT in `VALID_KEYS` (they aren't in the current set — leave `VALID_KEYS` unchanged so the generic `PUT /api/settings` can never write password material).

Add these endpoints to the router:

```python
class AuthUpdate(BaseModel):
    enabled: bool | None = None
    username: str | None = None
    password: str | None = None


@router.get("/auth")
async def get_auth_settings(db: AsyncSession = Depends(get_db)):
    enabled_row = await db.get(Setting, auth.AUTH_MAIN_ENABLED)
    user_row = await db.get(Setting, auth.AUTH_MAIN_USERNAME)
    return {
        "enabled": bool(enabled_row and enabled_row.value == "1"),
        "username": (user_row.value if user_row else "") or "",
    }


async def _set_setting(db: AsyncSession, key: str, value: str) -> None:
    row = await db.get(Setting, key)
    if row:
        row.value = value
    else:
        db.add(Setting(key=key, value=value))


@router.put("/auth")
async def update_auth_settings(body: AuthUpdate, db: AsyncSession = Depends(get_db)):
    # Update username if provided.
    if body.username is not None:
        await _set_setting(db, auth.AUTH_MAIN_USERNAME, body.username)
    # Update password hash only if a non-empty password was supplied.
    if body.password:
        await _set_setting(
            db, auth.AUTH_MAIN_PASSWORD_HASH, auth.hash_password(body.password)
        )

    # Determine effective credentials AFTER the above writes (not yet committed,
    # so read back from session state via get()).
    user_row = await db.get(Setting, auth.AUTH_MAIN_USERNAME)
    hash_row = await db.get(Setting, auth.AUTH_MAIN_PASSWORD_HASH)
    has_username = bool(user_row and user_row.value)
    has_password = bool(hash_row and hash_row.value)

    if body.enabled is not None:
        if body.enabled and not (has_username and has_password):
            await db.rollback()
            from fastapi import HTTPException

            raise HTTPException(
                status_code=400,
                detail="Set a username and password before enabling login.",
            )
        await _set_setting(db, auth.AUTH_MAIN_ENABLED, "1" if body.enabled else "0")

    await db.commit()
    auth.invalidate_main_auth_cache()
    return {"status": "saved"}
```

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/integration/test_auth_main.py -k auth_settings -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add app/routers/api_settings.py tests/integration/test_auth_main.py
git commit -m "feat(auth): add /api/settings/auth get+put with lock-out guard"
```

---

## Task 6: Main auth middleware

**Files:**
- Modify: `app/main.py` (add middleware after `app = FastAPI(...)` at `app/main.py:199`, before/after the static mount — order does not matter for `@app.middleware`)

- [ ] **Step 1: Write the failing integration tests (append to `tests/integration/test_auth_main.py`)**

```python
@pytest.mark.asyncio
async def test_healthz_open_even_when_auth_enabled(client):
    await client.put(
        "/api/settings/auth",
        json={"enabled": True, "username": "admin", "password": "hunter2"},
    )
    auth.invalidate_main_auth_cache()
    resp = await client.get("/healthz")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_protected_html_redirects_to_login(client):
    await client.put(
        "/api/settings/auth",
        json={"enabled": True, "username": "admin", "password": "hunter2"},
    )
    auth.invalidate_main_auth_cache()
    resp = await client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/login")


@pytest.mark.asyncio
async def test_protected_api_returns_401_json(client):
    await client.put(
        "/api/settings/auth",
        json={"enabled": True, "username": "admin", "password": "hunter2"},
    )
    auth.invalidate_main_auth_cache()
    resp = await client.get("/api/podcasts", follow_redirects=False)
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_then_access_then_logout(client):
    await client.put(
        "/api/settings/auth",
        json={"enabled": True, "username": "admin", "password": "hunter2"},
    )
    auth.invalidate_main_auth_cache()
    # Correct login sets cookie (httpx client persists cookies).
    login = await client.post(
        "/login",
        data={"username": "admin", "password": "hunter2"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    # Now the protected page is reachable.
    page = await client.get("/", follow_redirects=False)
    assert page.status_code == 200
    # Logout clears the cookie -> protected again.
    out = await client.post("/logout", follow_redirects=False)
    assert out.status_code == 303
    again = await client.get("/", follow_redirects=False)
    assert again.status_code == 303


@pytest.mark.asyncio
async def test_wrong_password_no_access(client):
    await client.put(
        "/api/settings/auth",
        json={"enabled": True, "username": "admin", "password": "hunter2"},
    )
    auth.invalidate_main_auth_cache()
    bad = await client.post(
        "/login",
        data={"username": "admin", "password": "WRONG"},
        follow_redirects=False,
    )
    assert bad.status_code == 401
    page = await client.get("/", follow_redirects=False)
    assert page.status_code == 303
```

Add `import contextlib` is not needed. Ensure the existing `test_main_auth_state_defaults_disabled` and earlier "default 200" expectations still hold: add one explicit default test at the top of the relevant section if not already present:

```python
@pytest.mark.asyncio
async def test_root_open_when_auth_disabled(client):
    auth.invalidate_main_auth_cache()
    # Ensure disabled (no enable performed in this test's own writes).
    await client.put("/api/settings/auth", json={"enabled": False})
    auth.invalidate_main_auth_cache()
    resp = await client.get("/", follow_redirects=False)
    assert resp.status_code == 200
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/integration/test_auth_main.py -k "redirect or 401_json or logout or wrong_password or healthz_open" -v`
Expected: FAIL — protected `/` returns 200 (no middleware yet), redirect/401 assertions fail.

- [ ] **Step 3: Add the middleware to `app/main.py`**

Add imports near the top of `app/main.py` (with the other imports):

```python
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse

from app import auth
from app.database import async_session
```

(`async_session` is already imported at `app/main.py:11` — do not duplicate. Add only `Request`, `JSONResponse`, `RedirectResponse`, and `from app import auth`.)

Immediately after `app = FastAPI(title=..., lifespan=lifespan)` (`app/main.py:199`), add:

```python
@app.middleware("http")
async def main_auth_guard(request: Request, call_next):
    path = request.url.path
    if path in auth.PUBLIC_PATHS or path.startswith(auth.PUBLIC_PREFIXES):
        return await call_next(request)

    async with async_session() as session:
        state = await auth.load_main_auth_state(session)

    if not state.enabled:
        return await call_next(request)

    token = request.cookies.get(auth.SESSION_COOKIE)
    payload = auth.verify_token(state.secret, token)
    if payload and payload.get("scope") == "main":
        return await call_next(request)

    if path.startswith("/api/"):
        return JSONResponse({"detail": "authentication required"}, status_code=401)
    return RedirectResponse(f"/login?next={path}", status_code=303)
```

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/integration/test_auth_main.py -v`
Expected: PASS (all main auth tests).

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `uv run pytest -q`
Expected: all tests pass. (The middleware is inert when auth is disabled, which is the default in other tests.)

- [ ] **Step 6: Commit**

```bash
git add app/main.py tests/integration/test_auth_main.py
git commit -m "feat(auth): enforce optional login via main auth middleware"
```

---

## Task 7: Portal auth columns + migration

**Files:**
- Modify: `app/models/portal.py:1-23`
- Create: `alembic/versions/0004_portal_auth.py`
- Test: `tests/integration/test_auth_portal.py`

- [ ] **Step 1: Add columns to the model**

Edit `app/models/portal.py` to add three columns and import `String` if not present (the file currently imports `Boolean, DateTime, Integer, Text, func`):

```python
from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
```

Add after the `enabled` column (`app/models/portal.py:22`):

```python
    auth_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="false")
    auth_username: Mapped[str | None] = mapped_column(String, nullable=True)
    auth_password_hash: Mapped[str | None] = mapped_column(String, nullable=True)
```

- [ ] **Step 2: Create the migration**

Create `alembic/versions/0004_portal_auth.py`:

```python
"""portal auth: per-portal optional username/password

Adds auth_enabled / auth_username / auth_password_hash to the portals table.
Idempotent (ADD COLUMN IF NOT EXISTS) so it is safe on fresh databases where
create_all already produced the columns and on legacy databases alike.

Revision ID: 0004_portal_auth
Revises: 0003_episode_perf_indexes
Create Date: 2026-06-14
"""

from __future__ import annotations

from alembic import op

revision = "0004_portal_auth"
down_revision = "0003_episode_perf_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE portals "
        "ADD COLUMN IF NOT EXISTS auth_enabled BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute("ALTER TABLE portals ADD COLUMN IF NOT EXISTS auth_username TEXT")
    op.execute("ALTER TABLE portals ADD COLUMN IF NOT EXISTS auth_password_hash TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE portals DROP COLUMN IF EXISTS auth_password_hash")
    op.execute("ALTER TABLE portals DROP COLUMN IF EXISTS auth_username")
    op.execute("ALTER TABLE portals DROP COLUMN IF EXISTS auth_enabled")
```

- [ ] **Step 3: Write a migration smoke test (new file `tests/integration/test_auth_portal.py`)**

```python
import pytest
from sqlalchemy import text


@pytest.mark.asyncio
async def test_portal_auth_columns_exist(db_session):
    # The session-scoped test_engine ran `alembic upgrade head`, which now
    # includes 0004_portal_auth.
    result = await db_session.execute(
        text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'portals' AND column_name IN "
            "('auth_enabled','auth_username','auth_password_hash')"
        )
    )
    cols = {row[0] for row in result.fetchall()}
    assert cols == {"auth_enabled", "auth_username", "auth_password_hash"}
```

- [ ] **Step 4: Run to verify it passes (migration runs in the conftest fixture)**

Run: `uv run pytest tests/integration/test_auth_portal.py -v`
Expected: PASS. (The `test_engine` fixture drops the schema and re-runs all migrations including `0004`.)

- [ ] **Step 5: Commit**

```bash
git add app/models/portal.py alembic/versions/0004_portal_auth.py tests/integration/test_auth_portal.py
git commit -m "feat(auth): add portal auth columns and 0004 migration"
```

---

## Task 8: Portal CRUD accepts/persists auth fields

**Files:**
- Modify: `app/routers/api_portals.py:18-25` (request model), `:31-45` (list), `:48-66` (create), `:74-85` (get), `:88-101` (update)

- [ ] **Step 1: Write the failing integration test (append to `tests/integration/test_auth_portal.py`)**

```python
@pytest.mark.asyncio
async def test_create_portal_with_auth_persists_hash_not_plain(client, db_session):
    from sqlalchemy import text

    resp = await client.post(
        "/api/portals",
        json={
            "title": "Secure Portal",
            "port": 9101,
            "podcast_ids": [],
            "auth_enabled": True,
            "auth_username": "guest",
            "auth_password": "letmein",
        },
    )
    assert resp.status_code == 200
    portal_id = resp.json()["id"]

    # Hash stored, not the raw password.
    row = await db_session.execute(
        text("SELECT auth_enabled, auth_username, auth_password_hash "
             "FROM portals WHERE id = :id"),
        {"id": portal_id},
    )
    enabled, username, pw_hash = row.fetchone()
    assert enabled is True
    assert username == "guest"
    assert pw_hash and pw_hash != "letmein"

    # API list/get never expose the hash or raw password.
    listed = (await client.get("/api/portals")).json()
    target = next(p for p in listed if p["id"] == portal_id)
    assert target["auth_enabled"] is True
    assert target["auth_username"] == "guest"
    assert "auth_password" not in target
    assert "auth_password_hash" not in target


@pytest.mark.asyncio
async def test_enable_portal_auth_without_credentials_rejected(client):
    resp = await client.post(
        "/api/portals",
        json={
            "title": "Bad Portal",
            "port": 9102,
            "podcast_ids": [],
            "auth_enabled": True,
        },
    )
    assert resp.status_code == 400
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/integration/test_auth_portal.py -k "with_auth or without_credentials" -v`
Expected: FAIL — create ignores auth fields; no 400 guard; list lacks `auth_enabled`.

- [ ] **Step 3: Update `app/routers/api_portals.py`**

Add import at the top (after existing imports):

```python
from fastapi import HTTPException

from app import auth
```

Extend `CreatePortalRequest` (`app/routers/api_portals.py:18-24`):

```python
class CreatePortalRequest(BaseModel):
    title: str
    port: int
    podcast_ids: list[str]
    description: str | None = None
    background_image: str | None = None
    secondary_image: str | None = None
    auth_enabled: bool = False
    auth_username: str | None = None
    auth_password: str | None = None
```

Add a shared serializer helper near the top of the module (after `router = APIRouter(...)`):

```python
def _portal_public_dict(p: Portal) -> dict:
    return {
        "id": str(p.id),
        "title": p.title,
        "slug": p.slug,
        "port": p.port,
        "podcast_ids": p.podcast_ids,
        "description": p.description,
        "background_image": p.background_image,
        "secondary_image": p.secondary_image,
        "enabled": p.enabled,
        "auth_enabled": p.auth_enabled,
        "auth_username": p.auth_username or "",
        "running": portal_manager.is_running(p.id),
    }
```

Replace the dict-building in `list_portals` and `get_portal` with `_portal_public_dict(p)` / `_portal_public_dict(portal)` respectively (the `not found` branch in `get_portal` stays unchanged).

In `create_portal`, after computing `slug` and before constructing `Portal`, add the lock-out guard and hashing:

```python
    if body.auth_enabled and not (body.auth_username and body.auth_password):
        raise HTTPException(
            status_code=400,
            detail="Set a username and password before enabling portal login.",
        )
    pw_hash = auth.hash_password(body.auth_password) if body.auth_password else None
    portal = Portal(
        title=body.title,
        slug=slug,
        port=body.port,
        podcast_ids=body.podcast_ids,
        description=body.description,
        background_image=body.background_image,
        secondary_image=body.secondary_image,
        auth_enabled=body.auth_enabled,
        auth_username=body.auth_username,
        auth_password_hash=pw_hash,
    )
```

In `update_portal`, extend the handled keys and add password/guard handling. Replace the loop body:

```python
    for key in ("title", "port", "podcast_ids", "description", "enabled",
                "background_image", "secondary_image", "auth_enabled", "auth_username"):
        if key in body:
            setattr(portal, key, body[key])
    # Hash a newly supplied portal password (non-empty only).
    if body.get("auth_password"):
        portal.auth_password_hash = auth.hash_password(body["auth_password"])
    # Lock-out guard: cannot end up enabled without username + a stored hash.
    if portal.auth_enabled and not (portal.auth_username and portal.auth_password_hash):
        await db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Set a username and password before enabling portal login.",
        )
    await db.commit()
    return {"status": "updated"}
```

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/integration/test_auth_portal.py -v`
Expected: PASS (all portal tests so far).

- [ ] **Step 5: Commit**

```bash
git add app/routers/api_portals.py tests/integration/test_auth_portal.py
git commit -m "feat(auth): persist and expose portal auth fields (hash-only)"
```

---

## Task 9: Portal app middleware + login routes

**Files:**
- Modify: `app/portal_server.py` (whole `create_app` — add startup credential load, middleware, `/login`, `/logout`)
- Test: append scope-isolation test to `tests/integration/test_auth_portal.py`

- [ ] **Step 1: Write the failing scope-isolation unit-style test (append to `tests/integration/test_auth_portal.py`)**

```python
def test_main_token_does_not_satisfy_portal_scope():
    from app import auth

    secret = "shared-secret"
    main_token = auth.sign_token(secret, {"scope": "main"})
    payload = auth.verify_token(secret, main_token)
    # A portal guard requires scope == "portal" AND matching id.
    assert not (payload.get("scope") == "portal")


def test_portal_token_roundtrip_scope_and_id():
    from app import auth

    secret = "shared-secret"
    token = auth.sign_token(secret, {"scope": "portal", "id": "abc-123"})
    payload = auth.verify_token(secret, token)
    assert payload == {"scope": "portal", "id": "abc-123"}
```

- [ ] **Step 2: Run to verify passing of these two (they only exercise `app.auth`, already implemented)**

Run: `uv run pytest tests/integration/test_auth_portal.py -k "scope" -v`
Expected: PASS. (These lock in the isolation contract the portal middleware will rely on.)

- [ ] **Step 3: Update `app/portal_server.py`**

Replace the body of `create_app()` so it loads credentials at startup, adds the guard middleware, and serves `/login` + `/logout`. Full updated file:

```python
import os
import uuid
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import auth
from app.config import settings


def create_app() -> FastAPI:  # noqa: F821  (FastAPI imported below)
    from fastapi import FastAPI

    portal_id = uuid.UUID(os.environ["PORTAL_ID"])
    app = FastAPI(title="Portal")

    # Load this portal's auth config + the shared signing secret once at startup.
    # portal_manager restarts the process on edit, so this stays fresh enough.
    import asyncio

    async def _load_auth():
        from app.database import async_session
        from app.models.portal import Portal

        async with async_session() as session:
            portal = await session.get(Portal, portal_id)
            secret = await auth.get_session_secret(session)
            if portal is None:
                return False, "", "", secret, "Portal"
            return (
                bool(portal.auth_enabled),
                portal.auth_username or "",
                portal.auth_password_hash or "",
                secret,
                portal.title,
            )

    auth_enabled, auth_username, auth_password_hash, session_secret, portal_title = (
        asyncio.run(_load_auth())
    )

    portal_public = {"/login", "/logout"}
    portal_prefixes = ("/static",)

    templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

    @app.middleware("http")
    async def portal_auth_guard(request: Request, call_next):
        if not auth_enabled:
            return await call_next(request)
        path = request.url.path
        if path in portal_public or path.startswith(portal_prefixes):
            return await call_next(request)
        token = request.cookies.get(auth.SESSION_COOKIE)
        payload = auth.verify_token(session_secret, token)
        if payload and payload.get("scope") == "portal" and payload.get("id") == str(portal_id):
            return await call_next(request)
        return RedirectResponse(f"/login?next={path}", status_code=303)

    static_dir = Path(settings.portal_images_dir)
    static_dir.mkdir(exist_ok=True)
    if static_dir.exists():
        app.mount("/static/portal_images", StaticFiles(directory=str(static_dir)), name="portal_images")

    app_static = Path(__file__).parent / "static"
    if app_static.exists():
        app.mount("/static", StaticFiles(directory=str(app_static)), name="static")

    from app.routers import api_episodes, api_insights, api_search

    app.include_router(api_search.router)
    app.include_router(api_episodes.router)
    app.include_router(api_insights.router)

    portal_router = APIRouter()

    def _safe_next(next_path: str | None) -> str:
        if next_path and next_path.startswith("/") and not next_path.startswith("//"):
            return next_path
        return "/"

    @portal_router.get("/login", response_class=HTMLResponse)
    async def portal_login_page(request: Request, next: str = "/"):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"title": portal_title, "next_path": _safe_next(next), "error": None},
        )

    @portal_router.post("/login")
    async def portal_login_submit(
        request: Request,
        username: str = Form(""),
        password: str = Form(""),
        next: str = Form("/"),
    ):
        ok = username == auth_username and auth.verify_password(password, auth_password_hash)
        if not ok:
            return templates.TemplateResponse(
                request,
                "login.html",
                {"title": portal_title, "next_path": _safe_next(next),
                 "error": "Invalid username or password."},
                status_code=401,
            )
        token = auth.sign_token(session_secret, {"scope": "portal", "id": str(portal_id)})
        resp = RedirectResponse(_safe_next(next), status_code=303)
        resp.set_cookie(auth.SESSION_COOKIE, token, httponly=True, samesite="lax", path="/")
        return resp

    @portal_router.post("/logout")
    async def portal_logout():
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(auth.SESSION_COOKIE, path="/")
        return resp

    @portal_router.get("/", response_class=HTMLResponse)
    async def portal_home(request: Request):
        from app.database import async_session
        from app.models.portal import Portal

        async with async_session() as session:
            portal = await session.get(Portal, portal_id)
            if not portal:
                return HTMLResponse("Portal not found", status_code=404)
        return templates.TemplateResponse(request, "portal_home.html", context={"portal": portal})

    @portal_router.get("/episodes/{episode_id}", response_class=HTMLResponse)
    async def portal_episode(request: Request, episode_id: str):
        from app.database import async_session
        from app.models.portal import Portal

        async with async_session() as session:
            portal = await session.get(Portal, portal_id)
        return templates.TemplateResponse(
            request, "portal_episode.html", context={"portal": portal, "episode_id": episode_id}
        )

    @portal_router.get("/insights", response_class=HTMLResponse)
    async def portal_insights_redirect():
        return RedirectResponse(url="/#insights", status_code=302)

    app.include_router(portal_router)
    return app
```

Note on the `FastAPI` import: the original imported `FastAPI` at module top. The version above imports it inside `create_app` to keep the `asyncio.run` startup self-contained; move the import back to module top (`from fastapi import FastAPI`) and drop the inner import + the `# noqa` if you prefer a cleaner top-level import — both work. Pick one and keep ruff happy.

- [ ] **Step 4: Lint the portal server**

Run: `uv run ruff check app/portal_server.py`
Expected: no errors. Fix import ordering / unused imports if flagged (e.g., settle the `FastAPI` import location).

- [ ] **Step 5: Run the portal test file**

Run: `uv run pytest tests/integration/test_auth_portal.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/portal_server.py tests/integration/test_auth_portal.py
git commit -m "feat(auth): add portal login routes and scoped auth middleware"
```

---

## Task 10: Nav logout button (main)

**Files:**
- Modify: `app/routers/ui.py` (add `main_auth_enabled` to template contexts)
- Modify: `app/templates/base.html:629-635` (nav)

- [ ] **Step 1: Confirm the `ui.py` handlers are async (they are)**

All handlers in `app/routers/ui.py` are `async def` and use
`templates.TemplateResponse(request, "<name>.html", ...)`. The nav-bearing
pages are `dashboard` (`/`), `search_page` (`/search`), `queue_page`
(`/queue`), and `admin_page` (`/admin`). We add `main_auth_enabled` to each.

- [ ] **Step 2: Add a context helper + wire all nav pages in `app/routers/ui.py`**

Add imports + helper at module level (after `templates = Jinja2Templates(...)`
at `app/routers/ui.py:8`):

```python
from app import auth
from app.database import async_session


async def _main_auth_enabled() -> bool:
    async with async_session() as session:
        state = await auth.load_main_auth_state(session)
    return state.enabled
```

Then update the four nav-bearing handlers to pass the flag. Replace each
listed return with the version that includes `main_auth_enabled`:

`dashboard` (`:11-13`):

```python
@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(
        request, "dashboard.html",
        context={"main_auth_enabled": await _main_auth_enabled()},
    )
```

`search_page` (`:34-36`):

```python
@router.get("/search", response_class=HTMLResponse)
async def search_page(request: Request):
    return templates.TemplateResponse(
        request, "search.html",
        context={"main_auth_enabled": await _main_auth_enabled()},
    )
```

`queue_page` (`:39-41`):

```python
@router.get("/queue", response_class=HTMLResponse)
async def queue_page(request: Request):
    return templates.TemplateResponse(
        request, "queue.html",
        context={"main_auth_enabled": await _main_auth_enabled()},
    )
```

`admin_page` (`:44-46`):

```python
@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    return templates.TemplateResponse(
        request, "admin.html",
        context={"main_auth_enabled": await _main_auth_enabled()},
    )
```

(Detail pages `podcast_detail`, `episode_view`, `library_detail` also extend
`base.html`; adding the key there is optional and harmless. For consistency
you may add `"main_auth_enabled": await _main_auth_enabled()` into their
existing `context={...}` dicts too — the button then shows on every page.)

- [ ] **Step 3: Add the conditional logout control to `app/templates/base.html`**

Replace the `<nav>` block (`app/templates/base.html:629-635`) with:

```html
  <nav class="nav-bar">
    <a href="/" class="nav-brand">Transcribe</a>
    <a href="/" class="nav-link active" id="nav-dashboard">Dashboard</a>
    <a href="/queue" class="nav-link" id="nav-queue">Queue</a>
    <a href="/search" class="nav-link" id="nav-search">Search &amp; Insights</a>
    <a href="/admin" class="nav-link" id="nav-admin">Admin</a>
    {% if main_auth_enabled %}
    <form method="post" action="/logout" style="margin-left:auto;">
      <button type="submit" class="nav-link" style="background:none;border:none;cursor:pointer;">Log out</button>
    </form>
    {% endif %}
  </nav>
```

(The `{% if main_auth_enabled %}` is simply falsy when the key is absent, so pages that don't pass it render no button — safe.)

- [ ] **Step 4: Manual smoke check (no automated test for nav HTML)**

Run: `uv run pytest tests/integration/test_auth_main.py -v`
Expected: still PASS (template change is backward-compatible; absent context key hides the button).

- [ ] **Step 5: Commit**

```bash
git add app/routers/ui.py app/templates/base.html
git commit -m "feat(auth): show logout in nav when main auth is enabled"
```

---

## Task 11: Admin UI — Authentication card + portal auth fields

**Files:**
- Modify: `app/templates/admin.html` (add Authentication card; extend portal form + list + Alpine state)

- [ ] **Step 1: Add the Authentication card markup**

Insert this card as the first child inside `<div class="flex flex-col gap-6" ...>` (before the Audiobookshelf card at `app/templates/admin.html:8`):

```html
    <!-- Authentication (main site) -->
    <div class="card" style="padding:20px;">
      <h2 class="section-title mb-3">Authentication</h2>
      <div class="flex flex-col gap-3">
        <label class="flex items-center gap-3 text-sm cursor-pointer">
          <input type="checkbox" x-model="auth.enabled" class="checkbox">
          <span class="font-medium">Require login for this admin site</span>
        </label>
        <div>
          <label class="text-xs font-medium text-secondary" style="display:block;margin-bottom:4px;">Username</label>
          <input type="text" x-model="auth.username" class="input" placeholder="admin">
        </div>
        <div>
          <label class="text-xs font-medium text-secondary" style="display:block;margin-bottom:4px;">Password</label>
          <input type="password" x-model="auth.password" class="input" :placeholder="auth.hasPassword ? '•••• (unchanged)' : 'Set a password'">
        </div>
        <div class="flex items-center gap-3">
          <button @click="saveAuth()" :disabled="auth.saving" class="btn btn-primary" x-text="auth.saving ? 'Saving...' : 'Save'"></button>
          <span x-text="auth.status" class="text-sm font-medium" :class="auth.ok ? 'text-accent' : 'text-red'"></span>
        </div>
      </div>
    </div>
```

- [ ] **Step 2: Extend `adminView()` Alpine state + methods**

In the `adminView()` return object (`app/templates/admin.html:301`), add an `auth` block to the state (after `semanticThreshold: 0.40,`):

```javascript
    auth: { enabled: false, username: '', password: '', hasPassword: false, saving: false, status: '', ok: false },
```

In `loadSettings()` (after the existing settings load, before `await this.refreshReembedStatus();`), add:

```javascript
      try {
        const ar = await fetch('/api/settings/auth');
        if (ar.ok) {
          const adata = await ar.json();
          this.auth.enabled = !!adata.enabled;
          this.auth.username = adata.username || '';
          this.auth.hasPassword = !!adata.username; // username present implies configured
        }
      } catch (e) { /* ignore */ }
```

Add a `saveAuth()` method to the object (e.g., after `saveAndTestAbs()`):

```javascript
    async saveAuth() {
      this.auth.saving = true; this.auth.status = ''; this.auth.ok = false;
      const body = { enabled: this.auth.enabled, username: this.auth.username };
      if (this.auth.password) body.password = this.auth.password;
      const r = await fetch('/api/settings/auth', {
        method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
      });
      if (r.ok) {
        this.auth.ok = true; this.auth.status = 'Saved!';
        this.auth.password = '';
        this.auth.hasPassword = this.auth.hasPassword || !!this.auth.username;
        setTimeout(() => this.auth.status = '', 2000);
      } else {
        let detail = 'Error saving';
        try { detail = (await r.json()).detail || detail; } catch (e) {}
        this.auth.status = detail;
      }
      this.auth.saving = false;
    },
```

- [ ] **Step 3: Add portal auth fields to the portal form**

In the portal form (inside `portalManager()`'s markup), after the "Secondary Image URL" field block (`app/templates/admin.html:156-159`), add:

```html
          <label class="flex items-center gap-3 text-sm cursor-pointer" style="padding:4px 0;">
            <input type="checkbox" x-model="form.auth_enabled" class="checkbox">
            <span class="font-medium">Require login for this portal</span>
          </label>
          <div x-show="form.auth_enabled" class="flex flex-col gap-3">
            <div>
              <label class="text-xs font-medium text-secondary" style="display:block;margin-bottom:4px;">Portal username</label>
              <input x-model="form.auth_username" class="input" style="border-radius:6px;" placeholder="guest">
            </div>
            <div>
              <label class="text-xs font-medium text-secondary" style="display:block;margin-bottom:4px;">Portal password</label>
              <input x-model="form.auth_password" type="password" class="input" style="border-radius:6px;"
                     :placeholder="editing ? '•••• (unchanged)' : 'Set a password'">
            </div>
          </div>
```

- [ ] **Step 4: Extend `portalManager()` state, edit, create, update**

Update the default `form` (`app/templates/admin.html:229`) to include the new fields:

```javascript
    form: { title: '', port: 9001, description: '', podcast_ids: [], background_image: '', secondary_image: '', enabled: true, auth_enabled: false, auth_username: '', auth_password: '' },
```

In `editPortal(p)` (`:243-253`), extend the assigned `form`:

```javascript
      this.form = {
        title: p.title, port: p.port, description: p.description || '',
        podcast_ids: [...(p.podcast_ids || [])],
        background_image: p.background_image || '',
        secondary_image: p.secondary_image || '',
        enabled: p.enabled || false,
        auth_enabled: p.auth_enabled || false,
        auth_username: p.auth_username || '',
        auth_password: '',
      };
```

In both `createPortal()` and `updatePortal()`, the existing code already sends `this.form` as the JSON body, so the new fields flow through automatically. Just update the two `this.form = { ... }` reset lines (`:263` and `:273`) to include the new keys:

```javascript
      this.form = { title: '', port: 9001, description: '', podcast_ids: [], background_image: '', secondary_image: '', enabled: true, auth_enabled: false, auth_username: '', auth_password: '' };
```

- [ ] **Step 5: Add the lock badge to the portal list row**

In the portal list row (`app/templates/admin.html:192-199`), add a badge next to the Running badge:

```html
              <span class="badge" :class="p.running ? 'badge-green' : 'badge-gray'" x-text="p.running ? 'Running' : 'Stopped'"></span>
              <span x-show="p.auth_enabled" class="badge badge-yellow" title="Login required">🔒 Auth</span>
```

- [ ] **Step 6: Manual verification in the running stack**

Run:
```bash
docker compose up -d --build db web
```
Then open the admin page, confirm: Authentication card loads (enabled=off, empty username); set username+password, toggle on, Save → "Saved!"; reload → enabled persists; logging in works; portal form shows auth fields and the 🔒 badge after enabling. (No automated test for the Alpine UI; this is a manual smoke step.)

- [ ] **Step 7: Commit**

```bash
git add app/templates/admin.html
git commit -m "feat(auth): admin UI for main + per-portal login settings"
```

---

## Task 12: Full verification + lint + final commit

**Files:** none (verification only)

- [ ] **Step 1: Run ruff over the changed surface**

Run: `uv run ruff check app tests`
Expected: no errors. Fix any import-order/unused issues.

- [ ] **Step 2: Run the full test suite with coverage gate**

Run: `uv run pytest -q`
Expected: all tests pass, including the pre-existing SP0 suite (auth is disabled by default so existing tests are unaffected).

- [ ] **Step 3: Confirm default-off behavior end-to-end**

Run:
```bash
uv run pytest tests/integration/test_auth_main.py::test_root_open_when_auth_disabled -v
```
Expected: PASS — proves the default (no auth) path is intact.

- [ ] **Step 4: Update CHANGELOG / version if the repo tracks it**

Check whether `pyproject.toml` version or a changelog should bump (current version `0.19.2`). If the repo convention is to bump on features, set `version = "0.20.0"` and note the auth feature. If unsure, skip — do not invent a changelog file.

- [ ] **Step 5: Final commit (if version bumped)**

```bash
git add pyproject.toml
git commit -m "chore: bump version for optional auth feature"
```

---

## Self-Review notes (for the implementer)

- **Default-off invariant:** every middleware (main + portal) returns `call_next` immediately when its `enabled` flag is false. The pre-existing test suite runs with auth disabled, so it must stay green — Task 6 Step 5 and Task 12 Step 2 verify this.
- **Never leak secrets:** `GET /api/settings/auth` and the portal serializer return only `enabled` + `username`. Tests in Task 5 and Task 8 assert the hash/raw password are absent.
- **Lock-out guard** is enforced in three places: `PUT /api/settings/auth` (main), portal create, portal update. All three return HTTP 400 and roll back.
- **Migration numbering:** the new migration is `0004_portal_auth` (`0003` is already used by `0003_episode_perf_indexes`). `down_revision = "0003_episode_perf_indexes"`.
- **Cookie is not `Secure`** by design (mixed plain-HTTP IP:port + nginx). Documented in the spec; revisit when fully behind HTTPS.
- **Portal credential freshness:** loaded once at portal-process startup; editing a portal should be followed by Stop/Start (existing admin controls) to apply new credentials. Called out in the spec's operational notes.
