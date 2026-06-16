import os
import re
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import auth
from app.config import settings
from app.database import get_db
from app.models.portal import Portal
from app.portal_manager import portal_manager

router = APIRouter(prefix="/api/portals", tags=["portals"])


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


class UpdatePortalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    port: int | None = None
    podcast_ids: list[str] | None = None
    description: str | None = None
    enabled: bool | None = None
    background_image: str | None = None
    secondary_image: str | None = None
    auth_enabled: bool | None = None
    auth_username: str | None = None
    auth_password: str | None = None


def _portal_public_dict(portal: Portal) -> dict:
    return {
        "id": str(portal.id),
        "title": portal.title,
        "slug": portal.slug,
        "port": portal.port,
        "podcast_ids": portal.podcast_ids,
        "description": portal.description,
        "background_image": portal.background_image,
        "secondary_image": portal.secondary_image,
        "enabled": portal.enabled,
        "auth_enabled": portal.auth_enabled,
        "auth_username": portal.auth_username or "",
        "running": portal_manager.is_running(portal.id),
    }


@router.get("")
async def list_portals(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Portal).order_by(Portal.title))
    portals = result.scalars().all()
    return [_portal_public_dict(p) for p in portals]


@router.post("")
async def create_portal(
    body: CreatePortalRequest,
    db: AsyncSession = Depends(get_db),
):
    slug = re.sub(r"[^a-z0-9-]", "", body.title.lower().replace(" ", "-"))[:50]
    auth_username = body.auth_username.strip() if body.auth_username is not None else None
    auth_password = body.auth_password.strip() if body.auth_password is not None else None
    auth_username = auth_username or None
    auth_password = auth_password or None

    if body.auth_enabled and not (auth_username and auth_password):
        raise HTTPException(
            status_code=400,
            detail="Set a username and password before enabling portal login.",
        )
    pw_hash = auth.hash_password(auth_password) if auth_password else None
    portal = Portal(
        title=body.title,
        slug=slug,
        port=body.port,
        podcast_ids=body.podcast_ids,
        description=body.description,
        background_image=body.background_image,
        secondary_image=body.secondary_image,
        auth_enabled=body.auth_enabled,
        auth_username=auth_username,
        auth_password_hash=pw_hash,
    )
    db.add(portal)
    await db.commit()
    await db.refresh(portal)
    return {"id": str(portal.id), "title": portal.title, "slug": portal.slug}


@router.get("/{portal_id}")
async def get_portal(portal_id: UUID, db: AsyncSession = Depends(get_db)):
    portal = await db.get(Portal, portal_id)
    if not portal:
        return {"error": "not found"}
    return _portal_public_dict(portal)


@router.put("/{portal_id}")
async def update_portal(
    portal_id: UUID,
    body: UpdatePortalRequest,
    db: AsyncSession = Depends(get_db),
):
    portal = await db.get(Portal, portal_id)
    if not portal:
        return {"error": "not found"}
    payload = body.model_dump(exclude_unset=True)
    for key in (
        "title",
        "port",
        "podcast_ids",
        "description",
        "enabled",
        "background_image",
        "secondary_image",
        "auth_enabled",
    ):
        if key in payload:
            setattr(portal, key, payload[key])

    if "auth_username" in payload:
        username_value = payload["auth_username"]
        if isinstance(username_value, str):
            username_value = username_value.strip() or None
        portal.auth_username = username_value

    if "auth_password" in payload:
        password_value = payload["auth_password"]
        if isinstance(password_value, str) and password_value.strip():
            # Non-empty → update the stored hash
            portal.auth_password_hash = auth.hash_password(password_value.strip())
        # Empty string means "leave existing password unchanged";
        # the edit form always sends "" when the user hasn't typed a new password.

    if portal.auth_enabled and not (portal.auth_username and portal.auth_password_hash):
        await db.rollback()
        raise HTTPException(
            status_code=400,
            detail="Set a username and password before enabling portal login.",
        )

    await db.commit()
    return {"status": "updated"}


@router.delete("/{portal_id}")
async def delete_portal(portal_id: UUID, db: AsyncSession = Depends(get_db)):
    await portal_manager.stop(portal_id)
    portal = await db.get(Portal, portal_id)
    if portal:
        await db.delete(portal)
        await db.commit()
    return {"status": "deleted"}


@router.post("/{portal_id}/start")
async def start_portal(portal_id: UUID, db: AsyncSession = Depends(get_db)):
    portal = await db.get(Portal, portal_id)
    if not portal:
        return {"error": "not found"}
    await portal_manager.start(portal)
    return {"status": "started"}


@router.post("/{portal_id}/stop")
async def stop_portal(portal_id: UUID, db: AsyncSession = Depends(get_db)):
    await portal_manager.stop(portal_id)
    return {"status": "stopped"}


@router.post("/{portal_id}/upload-image")
async def upload_portal_image(
    portal_id: UUID,
    image_type: str = "background",
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    portal = await db.get(Portal, portal_id)
    if not portal:
        return {"error": "not found"}
    ext = os.path.splitext(file.filename or "image.jpg")[1] or ".jpg"
    filename = f"{portal.slug}-{image_type}{ext}"
    os.makedirs(settings.portal_images_dir, exist_ok=True)
    path = os.path.join(settings.portal_images_dir, filename)
    content = await file.read()
    with open(path, "wb") as f:
        f.write(content)
    if image_type == "background":
        portal.background_image = f"/static/portal_images/{filename}"
    else:
        portal.secondary_image = f"/static/portal_images/{filename}"
    await db.commit()
    return {
        "status": "uploaded",
        "path": portal.background_image or portal.secondary_image,
    }
