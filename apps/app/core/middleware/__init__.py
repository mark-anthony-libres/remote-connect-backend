
import uuid
from typing import Callable
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from apps.app.utils import get_func
from apps.app.utils.logger import Logger
from apps.app.utils.cache import delete_cache_key


from apps.app.core.cache_builder import CacheDecodeError


async def request_id_middleware(request: Request, call_next: Callable) -> Response:
    rid = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = rid
    response = await call_next(request)
    response.headers["x-request-id"] = rid
    return response


async def cache_decode_error_middleware(request, call_next):
    try:
        return await call_next(request)
    except CacheDecodeError as exc:
        Logger.error(f"[CacheDecodeError] Cache decode error for request {request.url.path}: {exc}")
        try:
            endpoint_func = get_func(request)
            cache_key = endpoint_func.cache_key(request)
            await delete_cache_key(cache_key)
            return JSONResponse(
                status_code=500,
                content={
                    "detail": "Cache decode error. Cache key deleted. Please retry your request.",
                    "error": str(exc),
                }
            )
        except Exception as delete_exc:
            return JSONResponse(
                status_code=500,
                content={
                    "detail": "Cache decode error. Failed to re create the cache key.",
                    "error": str(exc),
                    "delete_error": str(delete_exc)
                }
            )
        
