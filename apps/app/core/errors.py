import functools
import inspect
import logging
from typing import Any, Callable, Dict, Optional

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from apps.app.core.settings import settings
from apps.app.core.db_guard import DatabaseSessionBypassError
from apps.app.utils import log_exception_with_traceback

logger = logging.getLogger("app")

DATABASE_SESSION_BYPASS_STATUS_CODE = 423

class ErrorResponse(BaseModel):
    error: str
    detail: Optional[Any] = None
    request_id: Optional[str] = None
    status_code: Optional[int] = None


def _allowed_origin(request_origin: Optional[str]) -> Optional[str]:
    wildcard_configured = "*" in settings.cors_origins
    if settings.cors_allow_credentials:
        if wildcard_configured:
            return request_origin
        if request_origin and request_origin in settings.cors_origins:
            return request_origin
        return None

    if wildcard_configured:
        return "*"
    if request_origin and request_origin in settings.cors_origins:
        return request_origin
    return None


def build_cors_headers(request_origin: Optional[str]) -> Dict[str, str]:
    headers: Dict[str, str] = {}
    origin = _allowed_origin(request_origin)
    if origin:
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Headers"] = "*"
        headers["Access-Control-Allow-Methods"] = "*"
        if settings.cors_allow_credentials:
            headers["Access-Control-Allow-Credentials"] = "true"
    return headers


def json_error(
    status_code: int,
    error: str,
    detail: Any,
    request_id: Optional[str],
    request_origin: Optional[str] = None,
    extra_headers: Optional[Dict[str, str]] = None,
) -> JSONResponse:
    payload: Dict[str, Any] = ErrorResponse(error=error, detail=detail, request_id=request_id, status_code=status_code).model_dump()
    headers = build_cors_headers(request_origin)
    if extra_headers:
        headers.update(extra_headers)
    return JSONResponse(status_code=status_code, content=payload, headers=headers)


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.warning("HTTP exception path=%s detail=%s", request.url.path, getattr(exc, "detail", exc))
    request_id = getattr(request.state, "request_id", None)
    status_code = getattr(exc, "status_code", 500)
    detail = getattr(exc, "detail", "Unexpected error")
    return json_error(
        status_code=status_code,
        error="http_error",
        detail=detail,
        request_id=request_id,
        request_origin=request.headers.get("origin"),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception path=%s", request.url.path)
    request_id = getattr(request.state, "request_id", None)
    if isinstance(exc, DatabaseSessionBypassError):
        return json_error(
            status_code=DATABASE_SESSION_BYPASS_STATUS_CODE,
            error="database_session_bypass",
            detail=str(exc),
            request_id=request_id,
            request_origin=request.headers.get("origin"),
        )
    return json_error(
        status_code=500,
        error="server_error",
        detail="Unexpected error",
        request_id=request_id,
        request_origin=request.headers.get("origin"),
    )


def handle_route_errors(
    context: str,
    status_code: int = 500,
    detail: Optional[str] = None,
) -> Callable:
    """Log and translate unhandled route exceptions into an HTTPException so
    they flow through http_exception_handler's structured JSON response
    instead of each controller improvising its own error response.
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            try:
                return await func(*args, **kwargs)
            except HTTPException:
                # Already an intentional response (e.g. 401/404) - don't downgrade it to a 500.
                raise
            except DatabaseSessionBypassError as error:
                log_exception_with_traceback(error, context=context)
                raise HTTPException(status_code=DATABASE_SESSION_BYPASS_STATUS_CODE, detail=str(error)) from error
            except Exception as error:
                log_exception_with_traceback(error, context=context)
                raise HTTPException(status_code=status_code, detail=detail or context) from error

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except HTTPException:
                raise
            except DatabaseSessionBypassError as error:
                log_exception_with_traceback(error, context=context)
                raise HTTPException(status_code=DATABASE_SESSION_BYPASS_STATUS_CODE, detail=str(error)) from error
            except Exception as error:
                log_exception_with_traceback(error, context=context)
                raise HTTPException(status_code=status_code, detail=detail or context) from error

        return async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper
    return decorator


