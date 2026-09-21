from __future__ import annotations

from typing import Optional

from fastapi import status
from fastapi.responses import JSONResponse

from apps.app.core.errors import build_cors_headers

ACCOUNT_LOCKED_ERROR_CODE = "ACCOUNT_TEMPORARILY_LOCKED"
ACCOUNT_LOCKED_MESSAGE = (
    "Your account has been temporarily locked due to excessive API requests. "
    "Please contact your administrator."
)


def account_temporarily_locked_response(request_origin: Optional[str], retry_after_seconds: int) -> JSONResponse:
    headers = build_cors_headers(request_origin)
    headers["Retry-After"] = str(max(0, retry_after_seconds))
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "error": {
                "code": ACCOUNT_LOCKED_ERROR_CODE,
                "message": ACCOUNT_LOCKED_MESSAGE,
            }
        },
        headers=headers,
    )
