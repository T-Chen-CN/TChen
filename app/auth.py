from __future__ import annotations

import secrets
from functools import wraps
from typing import Any, Callable

from fastapi import HTTPException, Request, status
from fastapi.responses import RedirectResponse

from .config import CONFIG


def is_logged_in(request: Request) -> bool:
    return bool(request.session.get("logged_in"))


def verify_credentials(username: str, password: str) -> bool:
    return secrets.compare_digest(username, CONFIG.admin_username) and secrets.compare_digest(
        password, CONFIG.admin_password
    )


def require_api_login(request: Request) -> None:
    if not is_logged_in(request):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录。")


def require_page_login(handler: Callable[..., Any]):
    @wraps(handler)
    async def wrapped(request: Request, *args, **kwargs):
        if not is_logged_in(request):
            return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
        return await handler(request, *args, **kwargs)

    return wrapped
