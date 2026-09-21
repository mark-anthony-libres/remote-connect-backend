from __future__ import annotations

import os
from typing import Optional

from fastapi import Response
from starlette.requests import HTTPConnection

from apps.app.core.settings import settings

DEDICATED_WORKER_ENV_VAR = "IMPERSONATION_WORKER"


def is_impersonation_worker() -> bool:
    return os.environ.get(DEDICATED_WORKER_ENV_VAR) == "1"


def get_bearer_token(connection: HTTPConnection) -> Optional[str]:
    auth_header = connection.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()

    return connection.cookies.get(settings.auth_cookie_name)


def set_access_token_cookie(response: Response, token: str, max_age_seconds: Optional[int] = None) -> None:
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=max_age_seconds if max_age_seconds is not None else settings.jwt_access_token_minutes * 60,
        path="/",
        domain=settings.auth_cookie_domain or None,
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite=settings.auth_cookie_samesite,
    )


def clear_access_token_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.auth_cookie_name,
        path="/",
        domain=settings.auth_cookie_domain or None,
        secure=settings.auth_cookie_secure,
        httponly=True,
        samesite=settings.auth_cookie_samesite,
    )
