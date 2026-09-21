import logging

from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError

logger = logging.getLogger("app")

REDIS_FAIL_OPEN_EXCEPTIONS = (RedisConnectionError, RedisTimeoutError)


def log_rate_limiter_degraded(operation: str, exc: Exception, **context) -> None:
    context_str = " ".join(f"{key}={value}" for key, value in context.items())
    logger.warning(
        "RATE_LIMITER_DEGRADED: Redis unavailable during %s - rate limiter is degraded and "
        "intentionally failing open, allowing this request; rate limiting is temporarily not "
        "being enforced until Redis recovers. error_type=%s error=%s %s",
        operation,
        type(exc).__name__,
        exc,
        context_str,
    )
