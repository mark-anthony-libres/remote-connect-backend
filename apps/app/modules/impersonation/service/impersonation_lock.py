import json
import time
from dataclasses import asdict, dataclass
from typing import Optional

from apps.app.core.settings import settings
from apps.app.utils.redis import get_redis_init

IMPERSONATION_ACTIVE_KEY = "impersonation:active"
IMPERSONATION_LEASE_KEY = "impersonation:lease"

IMPERSONATION_LEASE_SECONDS = settings.impersonation_lease_ttl_seconds
IMPERSONATION_MAX_DURATION_SECONDS = settings.impersonation_max_lifetime_seconds


@dataclass
class ActiveImpersonation:
    impersonation_id: str
    admin_user_id: int
    target_user_id: int
    started_at: float
    ttl_seconds: int


_CLAIM_IMPERSONATION_SCRIPT = """
local active = redis.call('GET', KEYS[1])
local heartbeat = redis.call('GET', KEYS[2])
if active and heartbeat then
    return {0, ''}
end
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
redis.call('SET', KEYS[2], '1', 'EX', ARGV[3])
if active then
    return {1, active}
end
return {1, ''}
"""

_RELEASE_IMPERSONATION_SCRIPT = """
local raw = redis.call('GET', KEYS[1])
if not raw then
    return 0
end
local data = cjson.decode(raw)
if data.impersonation_id == ARGV[1] then
    redis.call('DEL', KEYS[1])
    redis.call('DEL', KEYS[2])
    return 1
end
return 0
"""

_CHECK_AND_REFRESH_HEARTBEAT_SCRIPT = """
local exists = redis.call('GET', KEYS[1])
if not exists then
    return 0
end
redis.call('SET', KEYS[1], '1', 'EX', ARGV[1])
return 1
"""


def try_claim_impersonation(
    active_impersonation: ActiveImpersonation,
) -> tuple[bool, Optional[ActiveImpersonation]]:
    with get_redis_init() as r:
        script = r.register_script(_CLAIM_IMPERSONATION_SCRIPT)
        claimed, replaced_raw = script(
            keys=[IMPERSONATION_ACTIVE_KEY, IMPERSONATION_LEASE_KEY],
            args=[
                json.dumps(asdict(active_impersonation)),
                active_impersonation.ttl_seconds,
                IMPERSONATION_LEASE_SECONDS,
            ],
        )
        replaced_impersonation = (
            ActiveImpersonation(**json.loads(replaced_raw)) if replaced_raw else None
        )
        return bool(claimed), replaced_impersonation


def refresh_worker_heartbeat() -> None:
    with get_redis_init() as r:
        r.set(IMPERSONATION_LEASE_KEY, "1", ex=IMPERSONATION_LEASE_SECONDS)


def is_worker_alive() -> bool:
    with get_redis_init() as r:
        return r.get(IMPERSONATION_LEASE_KEY) is not None


def lease_seconds_remaining() -> int:
    with get_redis_init() as r:
        ttl = r.ttl(IMPERSONATION_LEASE_KEY)
        return ttl if ttl and ttl > 0 else 0


def check_and_refresh_worker_heartbeat() -> bool:
    with get_redis_init() as r:
        script = r.register_script(_CHECK_AND_REFRESH_HEARTBEAT_SCRIPT)
        alive = script(keys=[IMPERSONATION_LEASE_KEY], args=[IMPERSONATION_LEASE_SECONDS])
        return bool(alive)


def get_active_impersonation() -> Optional[ActiveImpersonation]:
    with get_redis_init() as r:
        raw = r.get(IMPERSONATION_ACTIVE_KEY)
        return ActiveImpersonation(**json.loads(raw)) if raw else None


def release_impersonation(impersonation_id: str) -> bool:
    with get_redis_init() as r:
        script = r.register_script(_RELEASE_IMPERSONATION_SCRIPT)
        return bool(
            script(keys=[IMPERSONATION_ACTIVE_KEY, IMPERSONATION_LEASE_KEY], args=[impersonation_id])
        )


def seconds_remaining(active_impersonation: ActiveImpersonation) -> int:
    return max(
        0, int(active_impersonation.ttl_seconds - (time.time() - active_impersonation.started_at))
    )


def is_expired(active_impersonation: ActiveImpersonation) -> bool:
    return time.time() - active_impersonation.started_at > active_impersonation.ttl_seconds
