import os
import uuid
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import auth
from app.config import settings


def _is_portal_public_path(path: str) -> bool:
    is_static_public = path == "/static" or path.startswith("/static/")
    return path in auth.PUBLIC_PATHS or is_static_public


def _build_portal_login_redirect_target(path: str, query: str) -> str:
    next_target = path
    if query:
        next_target = f"{next_target}?{query}"
    return f"/login?{urlencode({'next': next_target})}"


def _portal_unauthorized_response(path: str, query: str):
    if path.startswith("/api/"):
        return JSONResponse({"detail": "authentication required"}, status_code=401)
    return RedirectResponse(_build_portal_login_redirect_target(path, query), status_code=303)


def create_app() -> FastAPI:
    portal_id = uuid.UUID(os.environ["PORTAL_ID"])
    app = FastAPI(title="Portal")
    templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

    @app.on_event("startup")
    async def load_portal_auth_state() -> None:
        from app.database import async_session
        from app.models.portal import Portal

        async with async_session() as session:
            portal = await session.get(Portal, portal_id)
            session_secret = await auth.get_session_secret(session)

        app.state.auth_enabled = bool(portal and portal.auth_enabled)
        app.state.auth_username = (portal.auth_username if portal else "") or ""
        app.state.auth_password_hash = (portal.auth_password_hash if portal else "") or ""
        app.state.portal_title = (portal.title if portal else "Portal")
        app.state.session_secret = session_secret

    @app.middleware("http")
    async def portal_auth_guard(request: Request, call_next):
        if not getattr(app.state, "auth_enabled", False):
            return await call_next(request)

        path = request.url.path
        if _is_portal_public_path(path):
            return await call_next(request)

        token = request.cookies.get(auth.SESSION_COOKIE)
        payload = auth.verify_token(getattr(app.state, "session_secret", ""), token)
        if (
            payload
            and payload.get("scope") == "portal"
            and payload.get("id") == str(portal_id)
        ):
            return await call_next(request)

        return _portal_unauthorized_response(path, request.url.query)

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

    from app.routers import api_insights

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
            {
                "title": getattr(app.state, "portal_title", "Portal"),
                "next_path": _safe_next(next),
                "error": None,
            },
        )

    @portal_router.post("/login")
    async def portal_login_submit(
        request: Request,
        username: str = Form(""),
        password: str = Form(""),
        next: str = Form("/"),
    ):
        ok = username == getattr(app.state, "auth_username", "") and auth.verify_password(
            password,
            getattr(app.state, "auth_password_hash", ""),
        )
        if not ok:
            return templates.TemplateResponse(
                request,
                "login.html",
                {
                    "title": getattr(app.state, "portal_title", "Portal"),
                    "next_path": _safe_next(next),
                    "error": "Invalid username or password.",
                },
                status_code=401,
            )

        token = auth.sign_token(
            getattr(app.state, "session_secret", ""),
            {"scope": "portal", "id": str(portal_id)},
        )
        response = RedirectResponse(_safe_next(next), status_code=303)
        response.set_cookie(
            auth.SESSION_COOKIE,
            token,
            httponly=True,
            samesite="lax",
            path="/",
        )
        return response

    @portal_router.post("/logout")
    async def portal_logout():
        response = RedirectResponse("/login", status_code=303)
        response.delete_cookie(auth.SESSION_COOKIE, path="/")
        return response

    @portal_router.get("/", response_class=HTMLResponse)
    async def portal_home(request: Request):
        from app.database import async_session
        from app.models.portal import Portal

        async with async_session() as session:
            portal = await session.get(Portal, portal_id)
            if not portal:
                return HTMLResponse("Portal not found", status_code=404)
        return templates.TemplateResponse(
            request,
            "portal_home.html",
            context={"portal": portal},
        )

    @portal_router.get("/episodes/{episode_id}", response_class=HTMLResponse)
    async def portal_episode(request: Request, episode_id: str):
        from app.database import async_session
        from app.models.portal import Portal

        async with async_session() as session:
            portal = await session.get(Portal, portal_id)
        return templates.TemplateResponse(
            request,
            "portal_episode.html",
            context={"portal": portal, "episode_id": episode_id},
        )

    @portal_router.get("/insights", response_class=HTMLResponse)
    async def portal_insights_redirect():
        return RedirectResponse(url="/#insights", status_code=302)

    app.include_router(portal_router)
    return app
