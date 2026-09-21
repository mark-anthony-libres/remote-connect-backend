from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware

from apps.app.core.errors import json_error
from apps.app.core.rate_limiting.limiter import SlidingWindowRateLimiter
from apps.app.core.rate_limiting.redis_fail_open import REDIS_FAIL_OPEN_EXCEPTIONS, log_rate_limiter_degraded
from apps.app.core.settings import settings
from apps.app.utils.async_redis import redis_set, redis_ttl
from infra.redis_keys import rate_limit_cooldown_prefix, rate_limit_prefix


class _RenewingCooldown:
    def __init__(self, cooldown_seconds: int):
        self._cooldown_seconds = cooldown_seconds

    async def is_active(self, key: str) -> bool:
        try:
            ttl = await redis_ttl(key)
        except REDIS_FAIL_OPEN_EXCEPTIONS as exc:
            log_rate_limiter_degraded("cooldown_is_active", exc, key=key)
            return False
        return ttl > 0

    async def start_or_renew(self, key: str) -> None:
        await redis_set(key, "1", ex=self._cooldown_seconds)


class PathRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, rate_limited_paths: set[str], rate_limit_overrides: dict[str, tuple[int, int]] = None):
        super().__init__(app)
        self._rate_limited_paths = rate_limited_paths
        self._rate_limit_overrides = rate_limit_overrides or {}
        self._limiter = SlidingWindowRateLimiter(
            settings.public_rate_limit_window_seconds,
            settings.public_rate_limit_max_requests,
        )
        self._cooldown_seconds = settings.public_rate_limit_cooldown_seconds
        self._cooldown = _RenewingCooldown(self._cooldown_seconds)

    @staticmethod
    def _client_ip(request: Request) -> str:
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _too_many_requests_response(self, request: Request):
        return json_error(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            error="rate_limited",
            detail="Too many requests. Please try again later.",
            request_id=getattr(request.state, "request_id", None),
            request_origin=request.headers.get("origin"),
            extra_headers={"Retry-After": str(self._cooldown_seconds)},
        )

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        normalized_path = request.url.path.rstrip("/") or "/"
        if normalized_path not in self._rate_limited_paths:
            return await call_next(request)

        client_key = f"{self._client_ip(request)}:{normalized_path}"
        cooldown_key = f"{rate_limit_cooldown_prefix}:{client_key}"

        if await self._cooldown.is_active(cooldown_key):
            await self._cooldown.start_or_renew(cooldown_key)
            return self._too_many_requests_response(request)

        window_seconds, max_hits = self._rate_limit_overrides.get(normalized_path, (None, None))

        hit_key = f"{rate_limit_prefix}:{client_key}"
        if not await self._limiter.try_record_hit(hit_key, window_seconds=window_seconds, max_hits=max_hits):
            await self._cooldown.start_or_renew(cooldown_key)
            return self._too_many_requests_response(request)

        return await call_next(request)
