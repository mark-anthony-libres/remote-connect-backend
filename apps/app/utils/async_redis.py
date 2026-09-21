from __future__ import annotations

from typing import Any, List, Optional

import redis.asyncio as aioredis

from apps.app.core.settings import settings

client = aioredis.from_url(
    settings.celery_broker_url,
    decode_responses=False,
    health_check_interval=30,
    socket_keepalive=True,
)


async def redis_get(key: str) -> Optional[bytes]:
    return await client.get(key)


async def redis_set(key: str, value: Any, ex: Optional[int] = None, nx: bool = False) -> bool:
    return bool(await client.set(key, value, ex=ex, nx=nx))


async def redis_delete(*keys: str) -> int:
    if not keys:
        return 0
    return await client.delete(*keys)


async def redis_exists(key: str) -> bool:
    return bool(await client.exists(key))


async def redis_ttl(key: str) -> int:
    return await client.ttl(key)


async def redis_llen(key: str) -> int:
    return await client.llen(key)


async def redis_lrange(key: str, start: int, end: int) -> List[bytes]:
    return await client.lrange(key, start, end)


async def redis_scan_keys(match: str) -> List[bytes]:
    return [key async for key in client.scan_iter(match=match)]


async def redis_publish(channel: str, message: str) -> None:
    await client.publish(channel, message)


def redis_pipeline():
    return client.pipeline()


def redis_register_script(script: str):
    return client.register_script(script)
