"""Authentication helpers: password hashing and signed session tokens.

Pure functions with no FastAPI coupling. Used by both the main app
(``app/main.py`` + ``app/routers/auth_ui.py``) and each portal app
(``app/portal_server.py``).
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

import bcrypt
from itsdangerous import BadData, URLSafeSerializer
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.setting import Setting

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

_MAIN_AUTH_TTL = 5.0
_main_auth_cache = {"state": None, "expires": 0.0}


def hash_password(plain: str) -> str:
    """Return a bcrypt hash for ``plain``."""
    try:
        hashed = bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt())
        return hashed.decode("utf-8")
    except (ValueError, TypeError, RuntimeError) as exc:
        raise RuntimeError("bcrypt backend unavailable") from exc


def verify_password(plain: str, hashed: str | None) -> bool:
    """Return True if ``plain`` matches ``hashed``. False on any error/empty."""
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError, RuntimeError):
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
    except (BadData, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def generate_secret() -> str:
    """Generate a fresh random secret for cookie signing."""
    return secrets.token_urlsafe(32)


async def get_session_secret(session: AsyncSession) -> str:
    """Read the shared cookie-signing secret, generating+persisting if absent."""
    row = await session.get(Setting, AUTH_SESSION_SECRET)
    if row and row.value:
        return row.value

    bind = session.bind
    if bind is None:
        raise RuntimeError("session is not bound")

    new_secret = generate_secret()
    stmt = insert(Setting).values(key=AUTH_SESSION_SECRET, value=new_secret)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Setting.key],
        set_={"value": func.coalesce(func.nullif(Setting.value, ""), stmt.excluded.value)},
    ).returning(Setting.value)

    session_factory = async_sessionmaker(
        bind=bind,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_factory() as provision_session:
        secret = (await provision_session.execute(stmt)).scalar_one()
        await provision_session.commit()

    return secret


@dataclass
class MainAuthState:
    enabled: bool
    username: str
    password_hash: str
    secret: str


def invalidate_main_auth_cache() -> None:
    """Force the next load_main_auth_state() call to hit the DB."""
    _main_auth_cache["state"] = None
    _main_auth_cache["expires"] = 0.0


async def load_main_auth_state(session: AsyncSession) -> MainAuthState:
    """Return cached main-auth config using a short TTL."""
    now = time.monotonic()
    cached = _main_auth_cache["state"]
    expires = _main_auth_cache["expires"]
    if cached is not None and isinstance(expires, float) and now < expires:
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
