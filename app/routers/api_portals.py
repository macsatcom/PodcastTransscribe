import os
import re
from uuid import UUID

from fastapi import APIRouter, Depends, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


@router.get("")
async def list_portals(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Portal).order_by(Portal.title))
    portals = result.scalars().all()
    return [
        {
            "id": str(p.id),
            "title": p.title,
            "slug": p.slug,
            "port": p.port,
            "podcast_ids": p.podcast_ids,
            "description": p.description,
            "background_image": p.background_image,
            "secondary_image": p.secondary_image,
            "enabled": p.enabled,
            "running": portal_manager.is_running(p.id),
        }
        for p in portals
    ]


@router.post("")
async def create_portal(
    body: CreatePortalRequest,
    db: AsyncSession = Depends(get_db),
):
    slug = re.sub(r"[^a-z0-9-]", "", body.title.lower().replace(" ", "-"))[:50]
    portal = Portal(
        title=body.title,
        slug=slug,
        port=body.port,
        podcast_ids=body.podcast_ids,
        description=body.description,
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
        "running": portal_manager.is_running(portal.id),
    }


@router.put("/{portal_id}")
async def update_portal(
    portal_id: UUID,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    portal = await db.get(Portal, portal_id)
    if not portal:
        return {"error": "not found"}
    for key in ("title", "port", "podcast_ids", "description", "enabled", "background_image", "secondary_image"):
        if key in body:
            setattr(portal, key, body[key])
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
    return {"status": "uploaded", "path": portal.background_image or portal.secondary_image}
