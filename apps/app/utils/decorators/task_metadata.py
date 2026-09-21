import inspect
import json
import os
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, NamedTuple
from apps.app.core.settings import settings
from apps.app.utils.redis import get_redis_init

_METADATA_KEY_PREFIX = settings.task_metadata_key_prefix
_MARKER_REGEX = re.compile(r"#\s*sym\s*:\s*([A-Za-z_][A-Za-z0-9_]*)")

class TaskMetadataState(NamedTuple):
    """Represents enqueue timestamp metadata stored in Redis."""

    last_enqueued_at: str


class RedisTaskMetadataStore:
    """Reads and writes task enqueue metadata in Redis."""

    def __init__(self, metadata_key: str, ttl_seconds: int | None = None):
        self.metadata_key = metadata_key
        self.ttl_seconds = ttl_seconds

    def read(self) -> TaskMetadataState | None:
        with get_redis_init() as redis_client:
            raw_value = redis_client.get(self.metadata_key)

        if not raw_value:
            return None

        try:
            data = json.loads(raw_value)
            last_enqueued_at = data.get("last_enqueued_at")
            if not last_enqueued_at:
                return None
            return TaskMetadataState(last_enqueued_at=last_enqueued_at)
        except (json.JSONDecodeError, TypeError):
            return None

    def write(self, state: TaskMetadataState) -> None:
        payload = json.dumps({"last_enqueued_at": state.last_enqueued_at})
        with get_redis_init() as redis_client:
            if self.ttl_seconds and self.ttl_seconds > 0:
                redis_client.set(self.metadata_key, payload, ex=self.ttl_seconds)
            else:
                redis_client.set(self.metadata_key, payload)

    def set_last_enqueued_at(self, last_enqueued_at: str | None = None) -> str:
        if last_enqueued_at is None:
            last_enqueued_at = datetime.now(timezone.utc).isoformat()
        self.write(TaskMetadataState(last_enqueued_at=last_enqueued_at))
        return last_enqueued_at


def _resolve_source_filename(func: Callable) -> str:
    source_file = inspect.getsourcefile(func) or "unknown.py"
    return Path(source_file).stem


def _resolve_symbol_name(func: Callable) -> str:
    try:
        source = inspect.getsource(func)
        match = _MARKER_REGEX.search(source)
        if match:
            return match.group(1)
    except OSError:
        pass
    return func.__name__


def _build_task_metadata_key(func: Callable) -> str:
    filename = _resolve_source_filename(func)
    symbol_name = _resolve_symbol_name(func)
    return f"{_METADATA_KEY_PREFIX}{filename}_{symbol_name}"


def _attach_task_metadata_accessors(target_func: Callable, store: RedisTaskMetadataStore) -> None:
    def get_task_metadata() -> dict | None:
        state = store.read()
        return {"last_enqueued_at": state.last_enqueued_at} if state else None

    def get_last_enqueued_at() -> str | None:
        state = store.read()
        return state.last_enqueued_at if state else None

    def set_last_enqueued_at(last_enqueued_at: str | None = None) -> str:
        return store.set_last_enqueued_at(last_enqueued_at)

    setattr(target_func, "__task_metadata_key__", store.metadata_key)
    setattr(target_func, "get_task_metadata", get_task_metadata)
    setattr(target_func, "get_last_enqueued_at", get_last_enqueued_at)
    setattr(target_func, "set_last_enqueued_at", set_last_enqueued_at)


def TaskMetadata(ttl_seconds: int | None = None) -> Callable:
    """Decorator that provides Redis-backed enqueue metadata accessors."""

    def decorator(func: Callable) -> Callable:
        metadata_key = _build_task_metadata_key(func)
        store = RedisTaskMetadataStore(metadata_key, ttl_seconds)
        _attach_task_metadata_accessors(func, store)
        return func

    return decorator
