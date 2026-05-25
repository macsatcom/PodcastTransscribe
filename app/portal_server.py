import os
import uuid
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings


def create_app() -> FastAPI:
    portal_id = uuid.UUID(os.environ["PORTAL_ID"])
    app = FastAPI(title="Portal")

    static_dir = Path(settings.portal_images_dir)
    static_dir.mkdir(exist_ok=True)
    if static_dir.exists():
        app.mount("/static/portal_images", StaticFiles(directory=str(static_dir)), name="portal_images")

    app_static = Path(__file__).parent / "static"
    if app_static.exists():
        app.mount("/static", StaticFiles(directory=str(app_static)), name="static")

    from app.routers import api_search
    app.include_router(api_search.router)

    from app.routers import api_episodes
    app.include_router(api_episodes.router)

    from fastapi import APIRouter, Request
    from fastapi.responses import HTMLResponse
    from fastapi.templating import Jinja2Templates

    portal_router = APIRouter()
    templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

    @portal_router.get("/", response_class=HTMLResponse)
    async def portal_home(request: Request):
        from app.database import async_session
        from app.models.portal import Portal
        async with async_session() as session:
            portal = await session.get(Portal, portal_id)
            if not portal:
                return HTMLResponse("Portal not found", status_code=404)
        return templates.TemplateResponse(
            request, "portal_search.html", context={"portal": portal},
        )

    @portal_router.get("/episodes/{episode_id}", response_class=HTMLResponse)
    async def portal_episode(request: Request, episode_id: str):
        from app.database import async_session
        from app.models.portal import Portal
        async with async_session() as session:
            portal = await session.get(Portal, portal_id)
        return templates.TemplateResponse(
            request, "portal_episode.html", context={"portal": portal, "episode_id": episode_id},
        )

    app.include_router(portal_router)
    return app
