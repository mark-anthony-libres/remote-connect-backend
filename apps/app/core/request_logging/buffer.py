from __future__ import annotations

import json
from typing import Any, Dict

from apps.app.core.db import session_factory
from apps.app.core.settings import settings
from apps.app.modules.user.repositories.user_request_log_summary_repository import UserRequestLogSummaryRepository
from apps.app.utils.async_redis import redis_delete, redis_llen, redis_lrange, redis_pipeline
from apps.app.utils.concurrency import run_maybe_async
from apps.app.utils.logger import Logger
from infra.redis_keys import request_log_prefix

MAX_BUFFERED_REQUESTS_PER_SESSION = 100


class UserRequestLogBuffer:
    def __init__(self, ttl_seconds: int):
        self._ttl_seconds = ttl_seconds

    @staticmethod
    def _key(user_id, session_id) -> str:
        return f"{request_log_prefix}:{session_id}:{user_id}"

    async def record(self, user_id, session_id, entry: Dict[str, Any]) -> None:
        key = self._key(user_id, session_id)

        if await redis_llen(key) > MAX_BUFFERED_REQUESTS_PER_SESSION:
            await self.flush_endpoint_summary(user_id, session_id)

        async with redis_pipeline() as pipe:
            pipe.rpush(key, json.dumps(entry))
            pipe.expire(key, self._ttl_seconds)
            await pipe.execute()

    async def get_endpoint_summary(self, user_id, session_id) -> Dict[str, Dict[bool, Dict[str, Any]]]:
        key = self._key(user_id, session_id)
        raw_entries = await redis_lrange(key, 0, -1)

        summary: Dict[str, Dict[bool, Dict[str, Any]]] = {}
        for raw_entry in raw_entries:
            parsed = json.loads(raw_entry)
            endpoint = parsed["endpoint"]
            is_cached = parsed["is_cached"]

            cache_group = summary.setdefault(endpoint, {})
            stats = cache_group.setdefault(
                is_cached,
                {"request_count": 0, "_total_response_time": 0.0},
            )
            stats["request_count"] += 1
            stats["_total_response_time"] += parsed["response_time"]

        for cache_group in summary.values():
            for stats in cache_group.values():
                stats["average_response_time"] = stats.pop("_total_response_time") / stats["request_count"]

        return summary

    async def flush_endpoint_summary(self, user_id, session_id) -> None:
        key = self._key(user_id, session_id)
        summary = await self.get_endpoint_summary(user_id, session_id)

        if summary:
            self._log_summary(summary)

            try:
                await run_maybe_async(self._persist_summary, user_id, session_id, summary)
            except Exception as exc:
                Logger.error(f"[UserRequestLogBuffer] Failed to persist endpoint summary: {exc}")

        await redis_delete(key)

    @staticmethod
    def _log_summary(summary: Dict[str, Dict[bool, Dict[str, Any]]]) -> None:
        for endpoint, cache_group in summary.items():
            for is_cached, stats in cache_group.items():
                Logger.info(
                    f"[UserRequestLogBuffer] session buffer capped, discarding - "
                    f"endpoint={endpoint} is_cached={is_cached} "
                    f"request_count={stats['request_count']} "
                    f"average_response_time={stats['average_response_time']:.3f}s"
                )

    @staticmethod
    def _persist_summary(user_id, session_id, summary: Dict[str, Dict[bool, Dict[str, Any]]]) -> None:
        db = session_factory()
        try:
            summary_repo = UserRequestLogSummaryRepository(db)
            for endpoint, cache_group in summary.items():
                for is_cached, stats in cache_group.items():
                    summary_repo.record_summary(
                        user_id=user_id,
                        session_id=session_id,
                        endpoint=endpoint,
                        is_cached=is_cached,
                        request_count=stats["request_count"],
                        average_response_time=stats["average_response_time"],
                    )
        finally:
            db.close()


user_request_log_buffer = UserRequestLogBuffer(settings.request_log_session_buffer_ttl_seconds)
