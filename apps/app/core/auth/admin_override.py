import json

from apps.app.utils.redis import redis_delete, redis_get, redis_set
from infra.redis_keys import admin_custom_permissions_prefix, admin_mode_suppressed_prefix

ADMIN_OVERRIDE_TTL_SECONDS = 60 * 60 * 24


def _key(user_id: int) -> str:
    return f"{admin_mode_suppressed_prefix}:{user_id}"


def suppress_admin_mode(user_id: int) -> None:
    redis_set(_key(user_id), "1", ex=ADMIN_OVERRIDE_TTL_SECONDS)


def restore_admin_mode(user_id: int) -> None:
    redis_delete(_key(user_id))


def is_admin_mode_suppressed(user_id: int) -> bool:
    return bool(redis_get(_key(user_id)))


def _custom_permissions_key(user_id: int) -> str:
    return f"{admin_custom_permissions_prefix}:{user_id}"


def set_custom_permissions(user_id: int, permissions: dict) -> None:
    redis_set(_custom_permissions_key(user_id), json.dumps(permissions), ex=ADMIN_OVERRIDE_TTL_SECONDS)


def clear_custom_permissions(user_id: int) -> None:
    redis_delete(_custom_permissions_key(user_id))


def get_custom_permissions(user_id: int) -> dict | None:
    raw = redis_get(_custom_permissions_key(user_id))
    return json.loads(raw) if raw else None
