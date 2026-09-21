import secrets
import string
import time
import uuid

from fastapi import HTTPException
from redis.exceptions import ConnectionError as RedisConnectionError, TimeoutError as RedisTimeoutError

from apps.app.core.settings import settings
from apps.app.modules.monitor.services.monitor_session_service import generate_and_email_monitor_link
from apps.app.utils.email import EmailUtil
from apps.app.utils.logger import Logger
from apps.app.utils.redis import get_redis_init, redis_get, redis_set, redis_set_nx
from infra.redis_keys import (
    monitor_access_key_prefix,
    monitor_access_request_block_prefix,
    monitor_access_request_count_prefix,
    monitor_access_request_emailed_prefix,
)

_KEY_ALPHABET = string.ascii_letters + string.digits
_KEY_GROUP_LENGTHS = (4, 3, 2)

_STORAGE_UNAVAILABLE_DETAIL = "Service is temporarily unavailable. Please contact your administrator."
_INVALID_KEY_DETAIL = "Invalid access key."
_BLOCKED_DETAIL = "You are temporarily blocked."

_RECORD_VIOLATION_SCRIPT = """
local block_key = KEYS[1]
local counter_key = KEYS[2]
local now = tonumber(ARGV[1])
local window_seconds = tonumber(ARGV[2])
local max_hits = tonumber(ARGV[3])
local initial_block_seconds = tonumber(ARGV[4])
local member = ARGV[5]

local existing_duration = redis.call('GET', block_key)
if existing_duration then
    local new_duration = math.floor(tonumber(existing_duration) * 2)
    redis.call('SET', block_key, new_duration, 'EX', new_duration)
    return {1, 1}
end

redis.call('ZREMRANGEBYSCORE', counter_key, '-inf', now - window_seconds)
local count = redis.call('ZCARD', counter_key)

if count >= max_hits then
    redis.call('SET', block_key, initial_block_seconds, 'EX', initial_block_seconds)
    redis.call('DEL', counter_key)
    return {1, 0}
end

redis.call('ZADD', counter_key, now, member)
redis.call('EXPIRE', counter_key, window_seconds)
return {0, 0}
"""


def _unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail=_STORAGE_UNAVAILABLE_DETAIL)


def _generate_access_key() -> str:
    groups = [
        "".join(secrets.choice(_KEY_ALPHABET) for _ in range(length))
        for length in _KEY_GROUP_LENGTHS
    ]
    return "-".join(groups)


def _access_key_redis_key(access_key: str) -> str:
    return f"{monitor_access_key_prefix}:{access_key}"


def is_access_key_valid(access_key: str) -> bool:
    try:
        return redis_get(_access_key_redis_key(access_key)) is not None
    except (RedisConnectionError, RedisTimeoutError) as exc:
        raise _unavailable() from exc


def _issue_and_email_access_key(requested_by: str) -> dict:
    access_key = _generate_access_key()

    try:
        redis_set(_access_key_redis_key(access_key), "1", ex=settings.monitor_access_key_ttl_seconds)
    except (RedisConnectionError, RedisTimeoutError) as exc:
        raise _unavailable() from exc

    Logger.info(
        f"[monitor] Issued a new monitor access key (requested_by={requested_by}, "
        f"expires_in_seconds={settings.monitor_access_key_ttl_seconds})"
    )

    try:
        html = EmailUtil.create_template("monitor_access_key_ready.html", {
            "accessKey": access_key,
            "expiresInHours": settings.monitor_access_key_ttl_seconds // 3600,
        })
        EmailUtil.send(
            to=settings.mail_default_to,
            subject="CentCom: Monitor Access Key",
            html=html,
        )
    except Exception as exc:
        Logger.warning(f"[monitor] Failed to email the new monitor access key: {exc}")

    return {
        "recipients": settings.mail_default_to,
        "expires_in_seconds": settings.monitor_access_key_ttl_seconds,
    }


def _record_violation(ip: str) -> dict:
    now = time.time()
    member = f"{now}:{uuid.uuid4().hex}"

    try:
        with get_redis_init() as r:
            record_violation = r.register_script(_RECORD_VIOLATION_SCRIPT)
            blocked, escalated = record_violation(
                keys=[
                    f"{monitor_access_request_block_prefix}:{ip}",
                    f"{monitor_access_request_count_prefix}:{ip}",
                ],
                args=[
                    now,
                    settings.monitor_access_request_window_seconds,
                    settings.monitor_access_request_max_unauthenticated,
                    settings.monitor_access_request_block_seconds,
                    member,
                ],
            )
    except (RedisConnectionError, RedisTimeoutError) as exc:
        raise _unavailable() from exc

    return {"blocked": bool(blocked), "escalated": bool(escalated)}


def _maybe_email_key_for_ip(ip: str, requested_by: str) -> None:
    emailed_key = f"{monitor_access_request_emailed_prefix}:{ip}"

    try:
        first_in_window = redis_set_nx(
            emailed_key, "1", ttl_seconds=settings.monitor_access_request_window_seconds
        )
    except (RedisConnectionError, RedisTimeoutError) as exc:
        raise _unavailable() from exc

    if first_in_window:
        _issue_and_email_access_key(requested_by)
    else:
        Logger.info(f"[monitor] access-request ip={ip} already emailed a key this window - skipping")


def evaluate_monitor_access_request(ip: str, access_key: str | None) -> dict:
    Logger.info(f"[monitor] access-request ip={ip} key_present={bool(access_key)}")

    if access_key and is_access_key_valid(access_key):
        Logger.info(f"[monitor] access-request ip={ip} result=granted - sending monitoring link")
        result = generate_and_email_monitor_link(requested_by=ip)
        return {
            "sent": True,
            "message" : "A monitor session link has been sent to the administrator.",
            "expires_in_seconds": result["expires_in_seconds"],
        }

    outcome = _record_violation(ip)
    if outcome["blocked"]:
        Logger.info(f"[monitor] access-request ip={ip} result=blocked escalated={outcome['escalated']}")
        raise HTTPException(status_code=403, detail=_BLOCKED_DETAIL)

    if access_key:
        Logger.info(f"[monitor] access-request ip={ip} result=invalid_key")
        raise HTTPException(status_code=401, detail=_INVALID_KEY_DETAIL)

    Logger.info(f"[monitor] access-request ip={ip} result=no_key_allowed - checking whether to email a new key")
    _maybe_email_key_for_ip(ip, requested_by=ip)
    return {"access": "pending", "detail": "An access key has been sent to the administrator."}
