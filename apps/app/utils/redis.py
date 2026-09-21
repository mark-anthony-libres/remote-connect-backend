import os
from contextlib import contextmanager

import redis as sync_redis
from apps.app.core.settings import settings


@contextmanager
def get_redis_init(decode_responses: bool = True):
    r = sync_redis.from_url(settings.celery_broker_url, decode_responses=decode_responses)
    try:
        yield r
    finally:
        r.close()


def redis_set(key: str, value: str, ex: int = None) -> None:
    with get_redis_init() as r:
        r.set(key, value, ex=ex)


def redis_get(key: str) -> str | None:
    with get_redis_init() as r:
        return r.get(key)


def redis_delete(key: str) -> int:
    with get_redis_init() as r:
        return r.delete(key)


def redis_set_nx(key: str, value: str, ttl_seconds: int = 60) -> bool:
    """Set key only if it doesn't exist (NX), with TTL. Returns True if set, False if already exists."""
    with get_redis_init() as r:
        return r.set(key, value, nx=True, ex=ttl_seconds) is not None


_DELETE_IF_VALUE_MATCHES_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


def redis_delete_if_value_matches(key: str, expected_value: str) -> bool:
    with get_redis_init() as r:
        delete_if_still_owned = r.register_script(_DELETE_IF_VALUE_MATCHES_SCRIPT)
        return bool(delete_if_still_owned(keys=[key], args=[expected_value]))


_CONSUME_ONCE_SCRIPT = """
if redis.call('GET', KEYS[1]) then
    return redis.call('DEL', KEYS[1])
end
return 0
"""


def redis_consume_once(key: str) -> bool:
    with get_redis_init() as r:
        consume = r.register_script(_CONSUME_ONCE_SCRIPT)
        return bool(consume(keys=[key]))
