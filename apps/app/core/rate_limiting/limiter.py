import time
import uuid

from apps.app.core.rate_limiting.redis_fail_open import REDIS_FAIL_OPEN_EXCEPTIONS, log_rate_limiter_degraded
from apps.app.utils.async_redis import redis_register_script

_SLIDING_WINDOW_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local max_hits = tonumber(ARGV[3])
local member = ARGV[4]

redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window)

if redis.call('ZCARD', key) >= max_hits then
    return 0
end

redis.call('ZADD', key, now, member)
redis.call('EXPIRE', key, window)
return 1
"""


class SlidingWindowRateLimiter:
    def __init__(self, window_seconds: int, max_hits: int):
        self.window_seconds = window_seconds
        self.max_hits = max_hits
        self._check_and_record = redis_register_script(_SLIDING_WINDOW_SCRIPT)

    async def try_record_hit(self, key: str, window_seconds: int = None, max_hits: int = None) -> bool:
        now = time.time()
        member = f"{now}:{uuid.uuid4().hex}"

        try:
            allowed = await self._check_and_record(
                keys=[key],
                args=[
                    now,
                    window_seconds if window_seconds is not None else self.window_seconds,
                    max_hits if max_hits is not None else self.max_hits,
                    member,
                ],
            )
        except REDIS_FAIL_OPEN_EXCEPTIONS as exc:
            log_rate_limiter_degraded("try_record_hit", exc, key=key)
            return True

        return bool(allowed)
