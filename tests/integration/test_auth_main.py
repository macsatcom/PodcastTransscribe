from urllib.parse import parse_qs, urlsplit

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker

from app import auth
from app.models.setting import Setting


@pytest_asyncio.fixture(autouse=True)
async def _reset_main_auth_state(db_session):
    keys = [
        auth.AUTH_MAIN_ENABLED,
        auth.AUTH_MAIN_USERNAME,
        auth.AUTH_MAIN_PASSWORD_HASH,
        auth.AUTH_SESSION_SECRET,
    ]
    for key in keys:
        row = await db_session.get(Setting, key)
        if row:
            await db_session.delete(row)
    await db_session.commit()
    auth.invalidate_main_auth_cache()
    yield
    auth.invalidate_main_auth_cache()


@pytest.mark.asyncio
async def test_get_session_secret_persists(db_session):
    secret1 = await auth.get_session_secret(db_session)
    assert isinstance(secret1, str) and len(secret1) >= 16

    secret2 = await auth.get_session_secret(db_session)
    assert secret1 == secret2


@pytest.mark.asyncio
async def test_main_auth_state_defaults_disabled(db_session):
    auth.invalidate_main_auth_cache()
    state = await auth.load_main_auth_state(db_session)

    assert state.enabled is False
    assert state.username == ""


@pytest.mark.asyncio
async def test_get_session_secret_does_not_commit_caller_pending_changes(db_session):
    pending = Setting(key="_pending_marker", value="not_committed")
    db_session.add(pending)

    secret = await auth.get_session_secret(db_session)
    assert isinstance(secret, str) and len(secret) >= 16

    maker = async_sessionmaker(db_session.bind, expire_on_commit=False)
    async with maker() as probe:
        persisted_pending = await probe.get(Setting, "_pending_marker")
        assert persisted_pending is None

        persisted_secret = await probe.get(Setting, auth.AUTH_SESSION_SECRET)
        assert persisted_secret is not None
        assert persisted_secret.value == secret


@pytest.mark.asyncio
async def test_get_session_secret_replaces_empty_existing_value(db_session):
    db_session.add(Setting(key=auth.AUTH_SESSION_SECRET, value=""))
    await db_session.commit()

    secret = await auth.get_session_secret(db_session)

    assert isinstance(secret, str) and len(secret) >= 16

    persisted_secret = await db_session.get(Setting, auth.AUTH_SESSION_SECRET)
    assert persisted_secret is not None
    assert persisted_secret.value == secret


@pytest.mark.asyncio
async def test_login_page_renders(client):
    resp = await client.get("/login")
    assert resp.status_code == 200
    assert "Sign in" in resp.text


@pytest.mark.asyncio
async def test_login_rejects_when_no_main_credentials(client, db_session):
    auth.invalidate_main_auth_cache()
    resp = await client.post(
        "/login",
        data={"username": "x", "password": "y"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_page_normalizes_unsafe_next_param(client):
    resp = await client.get("/login", params={"next": "https://evil.example/x"})

    assert resp.status_code == 200
    assert 'name="next" value="/"' in resp.text


@pytest.mark.asyncio
async def test_login_success_with_safe_next_sets_cookie_and_redirects(client, db_session):
    db_session.add_all(
        [
            Setting(key=auth.AUTH_MAIN_ENABLED, value="1"),
            Setting(key=auth.AUTH_MAIN_USERNAME, value="admin"),
            Setting(key=auth.AUTH_MAIN_PASSWORD_HASH, value=auth.hash_password("s3cret")),
        ]
    )
    await db_session.commit()

    auth.invalidate_main_auth_cache()
    resp = await client.post(
        "/login",
        data={"username": "admin", "password": "s3cret", "next": "/episodes"},
    )

    assert resp.status_code == 303
    assert resp.headers["location"] == "/episodes"
    assert auth.SESSION_COOKIE in resp.cookies
    set_cookie = resp.headers.get("set-cookie", "")
    assert f"{auth.SESSION_COOKIE}=" in set_cookie


@pytest.mark.asyncio
async def test_logout_clears_cookie_and_redirects(client):
    resp = await client.post("/logout")

    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"
    set_cookie = resp.headers.get("set-cookie", "")
    assert f"{auth.SESSION_COOKIE}=" in set_cookie
    assert "Max-Age=0" in set_cookie


@pytest.mark.asyncio
async def test_get_auth_settings_defaults(client):
    resp = await client.get("/api/settings/auth")

    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False
    assert body["username"] == ""


@pytest.mark.asyncio
async def test_put_auth_settings_enable_requires_credentials(client):
    resp = await client.put("/api/settings/auth", json={"enabled": True})

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_put_auth_settings_sets_credentials_and_never_returns_hash(client):
    resp = await client.put(
        "/api/settings/auth",
        json={"enabled": True, "username": "admin", "password": "hunter2"},
    )

    assert resp.status_code == 200

    login = await client.post(
        "/login",
        data={"username": "admin", "password": "hunter2"},
        follow_redirects=False,
    )
    assert login.status_code == 303

    got = await client.get("/api/settings/auth")
    body = got.json()
    assert body == {"enabled": True, "username": "admin"}
    assert "password" not in body
    assert "password_hash" not in body


@pytest.mark.asyncio
async def test_put_auth_settings_treats_explicit_empty_password_as_unchanged(client, db_session):
    original_hash = auth.hash_password("hunter2")
    db_session.add(Setting(key=auth.AUTH_MAIN_PASSWORD_HASH, value=original_hash))
    await db_session.commit()

    resp = await client.put(
        "/api/settings/auth",
        json={"password": "   "},
    )

    assert resp.status_code == 200

    hash_row = await db_session.get(Setting, auth.AUTH_MAIN_PASSWORD_HASH)
    assert hash_row is not None
    assert hash_row.value == original_hash


@pytest.mark.asyncio
async def test_put_auth_settings_rejects_enabling_with_whitespace_username(client):
    resp = await client.put(
        "/api/settings/auth",
        json={"enabled": True, "username": "   ", "password": "hunter2"},
    )

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_put_auth_settings_normalizes_username(client, db_session):
    resp = await client.put(
        "/api/settings/auth",
        json={"username": " admin "},
    )

    assert resp.status_code == 200

    user_row = await db_session.get(Setting, auth.AUTH_MAIN_USERNAME)
    assert user_row is not None
    assert user_row.value == "admin"


@pytest.mark.asyncio
async def test_put_auth_settings_rejects_blank_username_when_auth_already_enabled(client, db_session):
    db_session.add_all(
        [
            Setting(key=auth.AUTH_MAIN_ENABLED, value="1"),
            Setting(key=auth.AUTH_MAIN_USERNAME, value="admin"),
            Setting(key=auth.AUTH_MAIN_PASSWORD_HASH, value=auth.hash_password("hunter2")),
        ]
    )
    await db_session.commit()

    login = await client.post(
        "/login",
        data={"username": "admin", "password": "hunter2"},
        follow_redirects=False,
    )
    assert login.status_code == 303

    resp = await client.put(
        "/api/settings/auth",
        json={"username": "   "},
    )

    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_put_auth_settings_rejects_unknown_field(client):
    resp = await client.put(
        "/api/settings/auth",
        json={"enabled": True, "unexpected": "value"},
    )

    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_root_open_when_auth_disabled(client):
    auth.invalidate_main_auth_cache()
    await client.put("/api/settings/auth", json={"enabled": False})
    auth.invalidate_main_auth_cache()

    resp = await client.get("/", follow_redirects=False)

    assert resp.status_code == 200


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
async def test_protected_html_redirect_preserves_query_in_next_param(client):
    await client.put(
        "/api/settings/auth",
        json={"enabled": True, "username": "admin", "password": "hunter2"},
    )
    auth.invalidate_main_auth_cache()

    resp = await client.get("/episodes?sort=desc&page=2", follow_redirects=False)

    assert resp.status_code == 303
    location = resp.headers["location"]
    assert urlsplit(location).path == "/login"
    assert parse_qs(urlsplit(location).query).get("next") == ["/episodes?sort=desc&page=2"]


@pytest.mark.asyncio
async def test_protected_api_returns_401_json(client):
    await client.put(
        "/api/settings/auth",
        json={"enabled": True, "username": "admin", "password": "hunter2"},
    )
    auth.invalidate_main_auth_cache()

    resp = await client.get("/api/podcasts", follow_redirects=False)

    assert resp.status_code == 401
    assert resp.json() == {"detail": "authentication required"}


@pytest.mark.asyncio
async def test_staticity_is_protected_when_auth_enabled(client):
    await client.put(
        "/api/settings/auth",
        json={"enabled": True, "username": "admin", "password": "hunter2"},
    )
    auth.invalidate_main_auth_cache()

    resp = await client.get("/staticity", follow_redirects=False)

    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/login")


@pytest.mark.asyncio
async def test_login_then_access_then_logout(client):
    await client.put(
        "/api/settings/auth",
        json={"enabled": True, "username": "admin", "password": "hunter2"},
    )
    auth.invalidate_main_auth_cache()

    login = await client.post(
        "/login",
        data={"username": "admin", "password": "hunter2"},
        follow_redirects=False,
    )
    assert login.status_code == 303

    page = await client.get("/", follow_redirects=False)
    assert page.status_code == 200

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
