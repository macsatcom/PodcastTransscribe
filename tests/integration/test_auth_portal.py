import json
from urllib.parse import parse_qs, urlsplit

import pytest
import pytest_asyncio
from sqlalchemy import text

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
async def test_portal_auth_columns_exist(db_session):
    result = await db_session.execute(
        text(
            "SELECT column_name, is_nullable, column_default, data_type "
            "FROM information_schema.columns "
            "WHERE table_schema = 'public' "
            "AND table_name = 'portals' "
            "AND column_name IN ('auth_enabled','auth_username','auth_password_hash')"
        )
    )
    rows = {
        row[0]: {
            "is_nullable": row[1],
            "column_default": row[2],
            "data_type": row[3],
        }
        for row in result.fetchall()
    }

    assert set(rows) == {"auth_enabled", "auth_username", "auth_password_hash"}

    assert rows["auth_enabled"]["is_nullable"] == "NO"
    assert rows["auth_enabled"]["column_default"] is not None
    assert "false" in rows["auth_enabled"]["column_default"].lower()

    assert rows["auth_username"]["is_nullable"] == "YES"
    assert rows["auth_username"]["data_type"] == "text"

    assert rows["auth_password_hash"]["is_nullable"] == "YES"
    assert rows["auth_password_hash"]["data_type"] == "text"


@pytest.mark.asyncio
async def test_create_portal_with_auth_persists_hash_not_plain(client, db_session):
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

    row = await db_session.execute(
        text(
            "SELECT auth_enabled, auth_username, auth_password_hash "
            "FROM portals WHERE id = :id"
        ),
        {"id": portal_id},
    )
    enabled, username, pw_hash = row.fetchone()
    assert enabled is True
    assert username == "guest"
    assert pw_hash and pw_hash != "letmein"

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


@pytest.mark.asyncio
async def test_update_portal_can_enable_auth_and_store_hash(client, db_session):
    created = await client.post(
        "/api/portals",
        json={
            "title": "Update Secure Portal",
            "port": 9103,
            "podcast_ids": [],
        },
    )
    assert created.status_code == 200
    portal_id = created.json()["id"]

    resp = await client.put(
        f"/api/portals/{portal_id}",
        json={
            "auth_enabled": True,
            "auth_username": "  guest  ",
            "auth_password": "  letmein  ",
        },
    )
    assert resp.status_code == 200

    row = await db_session.execute(
        text(
            "SELECT auth_enabled, auth_username, auth_password_hash "
            "FROM portals WHERE id = :id"
        ),
        {"id": portal_id},
    )
    enabled, username, pw_hash = row.fetchone()
    assert enabled is True
    assert username == "guest"
    assert pw_hash and pw_hash != "letmein"

    detail = await client.get(f"/api/portals/{portal_id}")
    assert detail.status_code == 200
    payload = detail.json()
    assert payload["auth_enabled"] is True
    assert payload["auth_username"] == "guest"
    assert "auth_password" not in payload
    assert "auth_password_hash" not in payload


@pytest.mark.asyncio
async def test_update_enable_auth_with_missing_or_blank_credentials_rejected(client):
    created = await client.post(
        "/api/portals",
        json={
            "title": "Update Missing Creds Portal",
            "port": 9104,
            "podcast_ids": [],
        },
    )
    assert created.status_code == 200
    portal_id = created.json()["id"]

    missing_creds = await client.put(
        f"/api/portals/{portal_id}",
        json={"auth_enabled": True},
    )
    assert missing_creds.status_code == 400

    blank_username = await client.put(
        f"/api/portals/{portal_id}",
        json={
            "auth_enabled": True,
            "auth_username": "   ",
            "auth_password": "letmein",
        },
    )
    assert blank_username.status_code == 400

    blank_password = await client.put(
        f"/api/portals/{portal_id}",
        json={
            "auth_enabled": True,
            "auth_username": "guest",
            "auth_password": "   ",
        },
    )
    assert blank_password.status_code == 400


@pytest.mark.asyncio
async def test_update_with_blank_auth_password_is_explicitly_invalid(client):
    created = await client.post(
        "/api/portals",
        json={
            "title": "Update Blank Password Portal",
            "port": 9105,
            "podcast_ids": [],
            "auth_enabled": True,
            "auth_username": "guest",
            "auth_password": "letmein",
        },
    )
    assert created.status_code == 200
    portal_id = created.json()["id"]

    resp = await client.put(
        f"/api/portals/{portal_id}",
        json={"auth_password": "   "},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_update_portal_rejects_unknown_fields(client):
    created = await client.post(
        "/api/portals",
        json={
            "title": "Update Unknown Field Portal",
            "port": 9106,
            "podcast_ids": [],
        },
    )
    assert created.status_code == 200
    portal_id = created.json()["id"]

    resp = await client.put(
        f"/api/portals/{portal_id}",
        json={"unknown_field": "nope"},
    )
    assert resp.status_code == 422


def test_main_token_does_not_satisfy_portal_scope():
    from app import auth

    secret = "shared-secret"
    main_token = auth.sign_token(secret, {"scope": "main"})
    payload = auth.verify_token(secret, main_token)
    assert payload is not None
    assert not (payload.get("scope") == "portal")


def test_portal_token_roundtrip_scope_and_id():
    from app import auth

    secret = "shared-secret"
    token = auth.sign_token(secret, {"scope": "portal", "id": "abc-123"})
    payload = auth.verify_token(secret, token)
    assert payload == {"scope": "portal", "id": "abc-123"}


def test_portal_login_redirect_preserves_query_in_encoded_next_param():
    from app.portal_server import _build_portal_login_redirect_target

    location = _build_portal_login_redirect_target(
        "/episodes/ep-1",
        "sort=desc&page=2",
    )

    split = urlsplit(location)
    assert split.path == "/login"
    assert parse_qs(split.query).get("next") == ["/episodes/ep-1?sort=desc&page=2"]


def test_portal_public_path_check_rejects_static_lookalikes():
    from app.portal_server import _is_portal_public_path

    assert _is_portal_public_path("/static") is True
    assert _is_portal_public_path("/static/main.css") is True
    assert _is_portal_public_path("/staticx") is False
    assert _is_portal_public_path("/staticity") is False


def test_portal_unauthorized_api_returns_401_json():
    from app.portal_server import _portal_unauthorized_response

    response = _portal_unauthorized_response("/api/search", "q=term")

    assert response.status_code == 401
    assert json.loads(response.body) == {"detail": "authentication required"}
