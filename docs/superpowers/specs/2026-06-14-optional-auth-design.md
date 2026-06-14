# Optional Auth — Design (SP1)

Date: 2026-06-14
Status: Approved (design); ready for implementation plan.

## Goal

Add **optional** username/password authentication, configurable from the
admin UI, with **one user per scope**:

- One login for the **main system** (the FastAPI app on `:8002`).
- One **separate** login for **each portal** (separate processes on `:9001+`).

Default behavior is unchanged: **no auth**. Auth is opt-in per scope and
turned on/off from the admin Settings page (main) and the portal
create/edit form (portals). No public signup — credentials are
admin-provisioned only.

## Non-Goals

- Multiple users / roles / permissions per scope (explicitly 1 user each).
- Password reset emails, MFA, OAuth, SSO.
- Rate limiting / lockout (can be a later hardening pass).
- Protecting `/healthz` (must stay open for Docker healthcheck).

## Approach (chosen)

App-level login with a **signed session cookie** + **bcrypt** password
hashes stored in the database. No new infrastructure. Both main and portal
apps share the same mechanism; a `scope` field inside the signed token
isolates main sessions from portal sessions.

## Data Model

### Main system (existing `Setting` key/value table)

New settings keys (all optional; absence = disabled):

- `auth_main_enabled` — `"0"` or `"1"` (default treated as `"0"`).
- `auth_main_username` — string.
- `auth_main_password_hash` — bcrypt hash string.
- `auth_session_secret` — random secret used to sign cookies. Auto-generated
  on first use if absent; shared by main and all portals.

### Portal (existing `Portal` model — new columns)

- `auth_enabled: bool` — default `False`.
- `auth_username: str | None` — nullable.
- `auth_password_hash: str | None` — nullable.

A new Alembic migration `0003_portal_auth` adds these three columns with
idempotent guards (the repo's migration convention), defaulting
`auth_enabled` to `False` for existing rows.

## Session Mechanics

- Cookie name: `pts_session` (same name in main and portal apps).
- Token: `itsdangerous.URLSafeSerializer(secret, salt="pts-auth")` payload:
  - Main: `{"scope": "main"}`.
  - Portal: `{"scope": "portal", "id": "<portal_uuid>"}`.
- The `scope`/`id` check means a main cookie never grants portal access and a
  portal cookie never grants main access (and one portal's cookie does not
  grant access to another portal).
- Cookie flags: `HttpOnly`, `SameSite=Lax`, `Path=/`, session cookie (no
  `Max-Age`/`Expires` → cleared when browser closes). `Secure` is **not**
  set (deployment is mixed plain-HTTP IP:port + nginx; setting `Secure`
  would break plain-HTTP access).
- Logout clears the cookie.

## Backend

### New module `app/auth.py`

Pure helpers, no FastAPI coupling beyond types:

- `hash_password(pw: str) -> str` — bcrypt via `passlib`.
- `verify_password(pw: str, hashed: str) -> bool`.
- `async def get_session_secret(session) -> str` — read
  `auth_session_secret`; if absent, generate (`secrets.token_urlsafe(32)`),
  persist, return.
- `sign_token(secret: str, payload: dict) -> str`.
- `verify_token(secret: str, token: str) -> dict | None` — returns `None` on
  bad signature / malformed token (never raises).
- Constants: `SESSION_COOKIE = "pts_session"`,
  `PUBLIC_PREFIXES = ("/static",)`,
  `PUBLIC_PATHS = {"/healthz", "/login", "/logout"}`.

### Main login routes — new `app/routers/auth_ui.py`

Included in `app.main`:

- `GET /login` → render `login.html` standalone (no nav). Honors optional
  `?next=` query param (validated to be a local path starting with `/`).
- `POST /login` (form fields `username`, `password`, optional `next`):
  - Load `auth_main_username` / `auth_main_password_hash`.
  - If `verify_password` passes → set `pts_session` cookie with
    `{"scope":"main"}`, redirect (303) to `next` (if local) else `/`.
  - Else → re-render `login.html` with an error message, HTTP 401.
- `POST /logout` → delete cookie, redirect (303) to `/login`.

### Main auth middleware (in `app/main.py`)

`@app.middleware("http")`:

1. If main auth is disabled → pass through.
2. If `request.url.path` in `PUBLIC_PATHS` or starts with a `PUBLIC_PREFIXES`
   entry → pass through.
3. Read `pts_session`; if `verify_token` yields `{"scope":"main"}` → pass
   through.
4. Otherwise deny:
   - If path starts with `/api/` → `JSONResponse(status_code=401,
     {"detail":"authentication required"})`.
   - Else → `RedirectResponse("/login?next=<path>", 303)`.

**State caching:** the enabled flag + username + hash + secret are read via a
small cached accessor (≈5 s TTL, in-process) to avoid a DB round-trip on
every request. Cache is invalidated immediately when
`PUT /api/settings/auth` writes new values (so toggling on/off and changing
credentials takes effect without waiting for TTL).

### Main settings API (extend `app/routers/api_settings.py`)

- `GET /api/settings/auth` → `{"enabled": bool, "username": str}`.
  **Never** returns the hash or password.
- `PUT /api/settings/auth` (body `{enabled?: bool, username?: str,
  password?: str}`):
  - `password`: only hashed + stored when present and non-empty (empty =
    "leave unchanged").
  - Enabling (`enabled=true`) is rejected with HTTP 400 unless a username and
    a stored-or-supplied password both exist (prevents locking yourself out
    with empty credentials).
  - On success, invalidate the middleware auth cache.

`auth_main_*` and `auth_session_secret` are **excluded** from the existing
`VALID_KEYS` set, so the generic `PUT /api/settings` can never write them
directly (which would bypass hashing). All auth writes go exclusively through
the dedicated `GET`/`PUT /api/settings/auth` endpoints above, which hash the
password before storing it.

### Portal CRUD (extend `app/routers/api_portals.py`)

- `CreatePortalRequest` gains `auth_enabled: bool = False`,
  `auth_username: str | None = None`, `auth_password: str | None = None`.
- Create/update: when `auth_password` present and non-empty, hash and store
  into `auth_password_hash`; never echo it back.
- `list_portals` / `get_portal` responses include `auth_enabled` and
  `auth_username` (never the hash). A small `auth_enabled` boolean drives the
  "🔒" badge in the admin list.
- Enabling a portal's auth follows the same lock-out guard as main (must have
  username + password).

### Portal app (extend `app/portal_server.py`)

- Add the **same** middleware pattern, but expecting token
  `{"scope":"portal","id":str(portal_id)}`.
- At portal-app startup, the portal loads its own `auth_enabled` /
  `auth_username` / `auth_password_hash` from its `Portal` row **and** the
  shared `auth_session_secret` from settings, caching both in the app
  instance. The middleware uses these cached values (no per-request DB read).
  Because `portal_manager` restarts a portal process when it is edited,
  changed credentials take effect on the portal's next start — acceptable for
  this simple model.
- Add `/login`, `/logout` routes in the portal app rendering the same
  `login.html` (with the portal's title). On success the cookie carries the
  portal scope+id.
- Public paths for portals: `/healthz` is not served by portals, so the
  portal public set is `{"/login", "/logout"}` plus the `/static`,
  `/static/portal_images` prefixes.
- Session secret: portals read `auth_session_secret` from settings (shared,
  cached at startup); scope+id isolation keeps sessions separate.

## Frontend

### New `app/templates/login.html`

Minimal standalone page (does **not** extend the nav `base.html` chrome, or
extends a barebones version): centered card, app/portal `title`, `username`
field, `password` field, error message slot, submit button. Posts to
`/login` as a normal form (so it works without JS and the redirect flow is
browser-native). Hidden `next` field passed through.

### `app/templates/base.html` (main nav)

- Add a **Logout** control in the nav, rendered **only when main auth is
  enabled**. Implemented as a tiny inline `<form method="post"
  action="/logout">` with a button styled as a nav link (POST per design
  decision).
- The enabled flag is passed to templates via the existing UI router context
  (a helper that reads cached auth state).

### `app/templates/admin.html`

- New **"Authentication"** card (main scope), placed near the top:
  - Toggle/checkbox: "Require login for this admin site".
  - `username` text input.
  - `password` input (`type=password`), placeholder
    `•••• (unchanged)` when a password already exists.
  - Save button + status text.
  - Loads from `GET /api/settings/auth`; saves via `PUT
    /api/settings/auth`. Surfaces the 400 lock-out guard error inline.
- Portal create/edit form gains:
  - `auth_enabled` checkbox ("Require login for this portal").
  - `auth_username` text input.
  - `auth_password` password input (placeholder `•••• (unchanged)` on edit).
  - Portal list rows show a "🔒 Auth" badge when `auth_enabled`.

## Dependencies

Add to `pyproject.toml`:

- `passlib[bcrypt]` — password hashing.
- `itsdangerous` — signed cookie tokens.

(Pin versions consistent with the repo's existing pinning style.)

## Testing (pytest, integration-first to match SP0)

- `tests/test_auth_unit.py`:
  - `hash_password` / `verify_password` round-trip; wrong password fails.
  - `sign_token` / `verify_token` round-trip; tampered token → `None`;
    wrong-secret token → `None`.
- `tests/integration/test_auth_main.py`:
  - Default (no auth settings): `GET /` → 200; `GET /api/podcasts` → 200.
  - After `PUT /api/settings/auth {enabled:true, username, password}`:
    - `GET /` (no cookie) → 303 redirect to `/login`.
    - `GET /api/podcasts` (no cookie) → 401 JSON.
    - `/healthz` → 200 (still open).
  - `POST /login` correct creds → sets cookie; subsequent `GET /` → 200.
  - `POST /login` wrong password → 401, no cookie.
  - `POST /logout` → cookie cleared; `GET /` → 303 again.
  - Enabling with missing password → 400 (lock-out guard).
- `tests/integration/test_auth_portal.py`:
  - Creating/updating a portal with auth fields persists `auth_enabled` /
    `auth_username` and a non-empty `auth_password_hash`; the API never
    returns the hash or raw password.
  - A token with `{"scope":"main"}` does not satisfy a portal guard
    (scope isolation), verified at the `verify_token` + guard level.

## Security Notes / Trade-offs

- Cookies are **not** `Secure` because deployment includes plain-HTTP
  IP:port access. If/when everything is behind HTTPS, flip `Secure` on (a
  later setting could gate this). Documented as a known limitation.
- Passwords are bcrypt-hashed; raw passwords are never logged, returned, or
  stored.
- The shared `auth_session_secret` plus per-token `scope`/`id` is a
  deliberate simplification over per-scope secrets; it keeps configuration to
  a single auto-managed value while preserving isolation.
- No lockout/rate-limit in this pass — acceptable for a home-server, LAN /
  reverse-proxy context; can be added later without schema changes.

## Out-of-band Operational Notes

- Existing running portals must be **restarted** to pick up newly set portal
  credentials (consistent with how portals already reload on edit through
  `portal_manager`). The admin UI's existing Start/Stop already covers this.
- No environment variables are required; everything is DB-backed and managed
  from the UI, matching the project's "configure from web UI" preference.
