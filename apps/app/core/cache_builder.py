import functools
import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Request, HTTPException
from starlette.responses import Response
from fastapi_cache.decorator import cache
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from fastapi_cache.coder import JsonCoder, _T

from apps.app.utils.concurrency import run_maybe_async
from apps.app.core.auth.access_token import get_bearer_token
from apps.app.core.auth.decorators import IS_PUBLIC_KEY
from apps.app.core.auth.tokens import decode_token
from apps.app.utils.logger import Logger
from apps.app.core.settings import settings
from apps.app.utils.async_redis import client as shared_redis_client, redis_delete, redis_scan_keys
from apps.app.utils.redis import get_redis_init
from infra.redis_keys import cache_key_prefix

class CacheDecodeError(Exception):
    pass

class CacheNotFoundError(Exception):
    pass

class RedisCacheManager:
    def __init__(self):
        self.prefix = settings.cache_prefix

    async def initialize(self):
        Logger.info("[Cache] Connecting to Redis")
        FastAPICache.init(
            RedisBackend(shared_redis_client),
            prefix=self.prefix
        )

class SafeJsonCoder(JsonCoder):
    @classmethod
    def encode(cls, value):
        if isinstance(value, Response):
            raise TypeError("Uncacheable response type: starlette.responses.Response")

        def default(obj):
            if isinstance(obj, datetime):
                return obj.isoformat()
            raise TypeError(f"{type(obj)} not serializable")
        return json.dumps(value, default=default).encode()

    @classmethod
    def decode(cls, value: bytes, object_hook=None) -> _T:
        try:
            return json.loads(value.decode(), object_hook=object_hook)
        except Exception as e:
            raise CacheDecodeError(str(e))

class CacheKeyBuilder:
    def build(self, func, request: Request):
        if request is None:
            return f"{cache_key_prefix}:no-request:{func.__name__}"
        query = "&".join(
            f"{k}={v}" for k, v in sorted(request.query_params.items())
        )
        path = request.url.path
        group = self._route_group(path)
        user = self._user_scope(func, request)
        key = f"{cache_key_prefix}:{group}:{user}:{path}?{query}"
        Logger.info(f"[Cache] Key: {key}")
        return key

    def _route_group(self, path: str):
        parts = [p for p in path.split("/") if p]
        if parts and parts[0] == "api":
            return parts[1] if len(parts) > 1 else "root"
        return parts[0] if parts else "root"

    def _user_scope(self, func, request: Request):
        if not getattr(func, "_user_scope_enabled", False):
            return "global"
        if getattr(func, IS_PUBLIC_KEY, False):
            return "public"
        token = get_bearer_token(request)
        if not token:
            return "anonymous"
        try:
            payload = decode_token(token)
            return payload.get("sub", "anonymous")
        except Exception:
            return "anonymous"

class RequestDeduplicator:
    def __init__(self, redis):
        self.redis = redis

    async def run(self, key: str, coro):
        lock_key = f"lock:{key}"
        acquired = await self.redis.set(lock_key, "1", nx=True, ex=30)
        if not acquired:
            Logger.info(f"[Dedup] Waiting → {key}")
            for _ in range(50):
                await asyncio.sleep(0.2)
                if not await self.redis.exists(lock_key):
                    break
        try:
            return await coro()
        finally:
            if acquired:
                await self.redis.delete(lock_key)

class CacheService:
    def __init__(self):
        self.key_builder = CacheKeyBuilder()

    def build_key(self, func, request: Request):
        return self.key_builder.build(func, request)

    def get_backend(self):
        return FastAPICache.get_backend()

def cache_key_builder(func, namespace, request=None, response=None, *args, **kwargs):
    if request is None:
        raise ValueError("Request is required for cache key")
    return CacheService().build_key(func, request)

class CachedRouter(APIRouter):
    def get(self, path: str, disable_cache: bool = False, expire: int = None, user_scope=False, *args, **kwargs):
        original = super().get(path, *args, **kwargs)
        cache_expire = settings.cache_expire_seconds if expire is None else expire
        def decorator(func):
            if settings.cache_disable or disable_cache:
                Logger.warning(f"[Cache] Disabled → {path}")
                return original(func)
            @functools.wraps(func)
            async def wrapper(*a, **kw):
                request: Request = kw.get("request")
                if request is None:
                    for arg in a:
                        if isinstance(arg, Request):
                            request = arg
                            break

                cache_service = CacheService()
                key = cache_service.build_key(func, request)
                redis = cache_service.get_backend().redis
                dedup = RequestDeduplicator(redis)
                async def compute():
                    Logger.info(f"[Cache] MISS → {path}")
                    result = await run_maybe_async(func, *a, **kw)

                    if isinstance(result, Response):
                        detail = "Endpoint returned Response object; caching skipped."
                        if getattr(result, "body", None):
                            try:
                                detail = result.body.decode(errors="replace")
                            except Exception:
                                detail = str(result.body)

                        raise HTTPException(
                            status_code=result.status_code or 500,
                            detail=detail,
                        )

                    return result
                return await dedup.run(key, compute)

            wrapper._user_scope_enabled = user_scope
            cached = cache(
                expire=cache_expire,
                coder=SafeJsonCoder,
                key_builder=cache_key_builder
            )(wrapper)

            cached.cache_key = lambda request: CacheService().build_key(func, request)
            return original(cached)
        return decorator


async def remove_group_cache_async(group: str):
    pattern = f"{cache_key_prefix}:{group}:*"

    keys = await redis_scan_keys(pattern)
    if keys:
        await redis_delete(*keys)
        Logger.info(f"[Cache] Cleared {len(keys)} keys for group '{group}'")
    else:
        Logger.info(f"[Cache] No keys to clear for group '{group}'")


async def remove_user_cache_async(user_id):
    pattern = f"{cache_key_prefix}:*:{user_id}:*"

    keys = await redis_scan_keys(pattern)
    if keys:
        await redis_delete(*keys)
        Logger.info(f"[Cache] Cleared {len(keys)} keys for user '{user_id}'")
    else:
        Logger.info(f"[Cache] No keys to clear for user '{user_id}'")


def remove_user_cache_sync(user_id) -> None:
    pattern = f"{cache_key_prefix}:*:{user_id}:*"

    with get_redis_init() as r:
        keys = list(r.scan_iter(match=pattern))
        if keys:
            r.delete(*keys)
            Logger.info(f"[Cache] Cleared {len(keys)} keys for user '{user_id}'")
        else:
            Logger.info(f"[Cache] No keys to clear for user '{user_id}'")


def remove_group_cache_sync(group: str) -> None:
    pattern = f"{cache_key_prefix}:{group}:*"

    with get_redis_init() as r:
        keys = list(r.scan_iter(match=pattern))
        if keys:
            r.delete(*keys)
            Logger.info(f"[Cache] Cleared {len(keys)} keys for group '{group}'")
        else:
            Logger.info(f"[Cache] No keys to clear for group '{group}'")

