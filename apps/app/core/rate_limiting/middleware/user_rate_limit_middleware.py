import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from apps.app.core.rate_limiting.account_lock import account_temporarily_locked_response
from apps.app.core.rate_limiting.limiter import SlidingWindowRateLimiter
from apps.app.core.settings import settings
from apps.app.core.rate_limiting.user_blocking import user_block_store
from infra.redis_keys import user_request_rate_prefix

BLOCK_REASON = "exceeded_request_rate_limit"


class UserRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._rate_limiter = SlidingWindowRateLimiter(
            settings.user_rate_limit_window_seconds,
            settings.user_rate_limit_max_requests,
        )

    async def dispatch(self, request: Request, call_next):
        user_id = getattr(request.state, "user_id", None)
        if user_id is None:
            return await call_next(request)

        request_origin = request.headers.get("origin")

        existing_block = await user_block_store.get_active_block(user_id)
        if existing_block:
            retry_after = round(existing_block["expires_at"] - time.time())
            return account_temporarily_locked_response(request_origin, retry_after)

        key = f"{user_request_rate_prefix}:{user_id}"
        if not await self._rate_limiter.try_record_hit(key):
            new_block = await user_block_store.block_user(
                user_id, reason=BLOCK_REASON, ttl_seconds=settings.user_block_duration_seconds
            )
            retry_after = round(new_block["expires_at"] - time.time())
            return account_temporarily_locked_response(request_origin, retry_after)

        return await call_next(request)
