from pathlib import Path

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app import auth
from app.database import get_db

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory=Path(__file__).parent.parent / "templates")

MAIN_TITLE = "Transcribe Admin"


def _safe_next(next_path: str | None) -> str:
    if next_path and next_path.startswith("/") and not next_path.startswith("//"):
        return next_path
    return "/"


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next_path: str = Query("/", alias="next")):
    return templates.TemplateResponse(
        request,
        "login.html",
        {"title": MAIN_TITLE, "next_path": _safe_next(next_path), "error": None},
    )


@router.post("/login")
async def login_submit(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    next_path: str = Form("/", alias="next"),
    db: AsyncSession = Depends(get_db),
):
    state = await auth.load_main_auth_state(db)
    ok = username == state.username and auth.verify_password(password, state.password_hash)

    if not ok:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "title": MAIN_TITLE,
                "next_path": _safe_next(next_path),
                "error": "Invalid username or password.",
            },
            status_code=401,
        )

    token = auth.sign_token(state.secret, {"scope": "main"})
    response = RedirectResponse(_safe_next(next_path), status_code=303)
    response.set_cookie(
        auth.SESSION_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return response
