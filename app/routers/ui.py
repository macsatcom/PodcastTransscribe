from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app import auth
from app.database import async_session

router = APIRouter(tags=["ui"])
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")


async def _main_auth_enabled() -> bool:
    async with async_session() as session:
        state = await auth.load_main_auth_state(session)
    return state.enabled


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        context={"main_auth_enabled": await _main_auth_enabled()},
    )


@router.get("/podcasts/{podcast_id}", response_class=HTMLResponse)
async def podcast_detail(request: Request, podcast_id: str):
    return templates.TemplateResponse(
        request,
        "podcast_detail.html",
        context={
            "podcast_id": podcast_id,
            "main_auth_enabled": await _main_auth_enabled(),
        },
    )


@router.get("/episodes/{episode_id}", response_class=HTMLResponse)
async def episode_view(request: Request, episode_id: str):
    return templates.TemplateResponse(
        request,
        "episode.html",
        context={
            "episode_id": episode_id,
            "main_auth_enabled": await _main_auth_enabled(),
        },
    )


@router.get("/search", response_class=HTMLResponse)
async def search_page(request: Request):
    return templates.TemplateResponse(
        request,
        "search.html",
        context={"main_auth_enabled": await _main_auth_enabled()},
    )


@router.get("/queue", response_class=HTMLResponse)
async def queue_page(request: Request):
    return templates.TemplateResponse(
        request,
        "queue.html",
        context={"main_auth_enabled": await _main_auth_enabled()},
    )


@router.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    return templates.TemplateResponse(
        request,
        "admin.html",
        context={"main_auth_enabled": await _main_auth_enabled()},
    )


@router.get("/insights", response_class=HTMLResponse)
async def insights_redirect():
    return RedirectResponse(url="/search#insights", status_code=302)


@router.get("/library/{abs_item_id}", response_class=HTMLResponse)
async def library_detail(request: Request, abs_item_id: str):
    return templates.TemplateResponse(
        request,
        "library_detail.html",
        context={
            "abs_item_id": abs_item_id,
            "main_auth_enabled": await _main_auth_enabled(),
        },
    )
