from fastapi import Request, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from apps.app.core.rate_limiting.limiter import SlidingWindowRateLimiter
from apps.app.core.settings import settings


def resolve_client_ip(request: Request) -> str:
    direct_peer = request.client.host if request.client else "unknown"

    if direct_peer not in settings.monitor_trusted_proxy_ips:
        return direct_peer

    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return direct_peer


class MonitorRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._limiter = SlidingWindowRateLimiter(
            settings.monitor_rate_limit_window_seconds, settings.monitor_rate_limit_max_requests
        )

    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS" or str(settings.environment).lower() == "local":
            return await call_next(request)

        client_ip = resolve_client_ip(request)
        allowed = await self._limiter.try_record_hit(f"monitor-rate-limit:{client_ip}")

        if not allowed:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"error": "rate_limited", "detail": "Too many requests - slow down."},
            )

        return await call_next(request)
