from __future__ import annotations

import json
import time
from typing import Optional

from apps.app.core.rate_limiting.redis_fail_open import REDIS_FAIL_OPEN_EXCEPTIONS, log_rate_limiter_degraded
from apps.app.utils.async_redis import redis_get, redis_set
from infra.redis_keys import user_block_prefix


class UserBlockStore:
    @staticmethod
    def _key(user_id) -> str:
        return f"{user_block_prefix}:{user_id}"

    async def get_active_block(self, user_id) -> Optional[dict]:
        try:
            raw = await redis_get(self._key(user_id))
        except REDIS_FAIL_OPEN_EXCEPTIONS as exc:
            log_rate_limiter_degraded("get_active_block", exc, user_id=user_id)
            return None
        return json.loads(raw) if raw else None

    async def block_user(self, user_id, reason: str, ttl_seconds: int) -> dict:
        now = time.time()
        block = {
            "reason": reason,
            "blocked_at": now,
            "expires_at": now + ttl_seconds,
        }
        await redis_set(self._key(user_id), json.dumps(block), ex=ttl_seconds)
        return block


user_block_store = UserBlockStore()
