import json

from apps.app.core.settings import settings
from apps.app.utils.logger import Logger
from apps.app.utils.redis import get_redis_init


def _publish_invalidation_sync(payload: dict) -> None:
    try:
        with get_redis_init() as r:
            r.publish(settings.monitor_ws_invalidation_channel, json.dumps(payload))
    except Exception as exc:
        Logger.warning(f"[monitor.ws] Redis publish failed: {exc}")


def invalidate_group_sync(group: str) -> None:
    _publish_invalidation_sync({
        "type": "invalidate",
        "group": group,
    })


def invalidate_endpoint_sync(endpoint: str) -> None:
    _publish_invalidation_sync({
        "type": "invalidate",
        "endpoint": endpoint,
    })
