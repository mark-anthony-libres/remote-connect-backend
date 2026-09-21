import json

from apps.app.utils.logger import Logger
from apps.app.websocket.gateway import manager
from apps.app.core.settings import settings
from apps.app.utils.async_redis import redis_publish
from apps.app.utils.redis import get_redis_init


async def _publish_invalidation(payload: dict):
    try:
        await redis_publish(settings.ws_invalidation_channel, json.dumps(payload))
    except Exception as exc:
        Logger.warning(f"[WS] Redis publish failed, falling back to local broadcast: {exc}")
        await manager.broadcast(payload)


def _publish_invalidation_sync(payload: dict) -> None:
    try:
        with get_redis_init() as r:
            r.publish(settings.ws_invalidation_channel, json.dumps(payload))
    except Exception as exc:
        Logger.warning(f"[WS] Redis publish failed: {exc}")


async def invalidate_group(group: str):
    Logger.success(f"Sending notification for group: {group}")
    await _publish_invalidation({
        "type": "invalidate",
        "group": group,
    })


async def invalidate_endpoint(endpoint: str):
    Logger.success(f"Sending notification for endpoint: {endpoint}")
    await _publish_invalidation({
        "type": "invalidate",
        "endpoint": endpoint,
    })


def invalidate_group_sync(group: str) -> None:
    Logger.success(f"Sending notification for group: {group}")
    _publish_invalidation_sync({
        "type": "invalidate",
        "group": group,
    })


def invalidate_endpoint_sync(endpoint: str) -> None:
    Logger.success(f"Sending notification for endpoint: {endpoint}")
    _publish_invalidation_sync({
        "type": "invalidate",
        "endpoint": endpoint,
    })


async def invalidate_session(session_id: str):
    Logger.success(f"Revoking WS connections for session: {session_id}")
    await _publish_invalidation({
        "type": "revoke_session",
        "session_id": session_id,
    })


def invalidate_impersonation_sync(impersonation_id: str) -> None:
    Logger.success(f"Notifying browsers impersonation ended: {impersonation_id}")
    _publish_invalidation_sync({
        "type": "impersonation_invalid",
        "impersonation_id": impersonation_id,
    })