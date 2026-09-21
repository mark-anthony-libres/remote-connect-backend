from datetime import datetime, timezone
import uuid
from typing import Any, Callable
import json

from croniter import croniter

from apps.app.utils.logger import Logger
from apps.app.utils.redis import (
    get_redis_init,
    redis_delete,
    redis_delete_if_value_matches,
    redis_get,
    redis_set,
    redis_set_nx,
)

from apps.app.core.settings import settings

CeleryTask = Callable[..., Any]
TrackedFunction = Callable[..., Any]

UTC = timezone.utc

MAX_RUNNING_TASKS = settings.max_running_tasks
TASK_LOCK_TTL_SECONDS = settings.scheduler_stale_task_timeout_seconds
GLOBAL_SLOT_PREFIX = "scheduler:global-slot"
TASK_SLOT_MAP_PREFIX = "scheduler:task-slot"
TASK_LOCK_MAP_PREFIX = "scheduler:task-lock"

_CLAIM_FIRST_FREE_SLOT_SCRIPT = """
for _, key in ipairs(KEYS) do
    if redis.call('SET', key, ARGV[1], 'NX', 'EX', ARGV[2]) then
        return key
    end
end
return false
"""


def build_task_lock_key(task_name: str, tracking_key: str) -> str:
    return f"scheduler:inflight:{task_name}:{tracking_key}"


def reserve_task_slot() -> tuple[str, str] | tuple[None, None]:
    owner_token = uuid.uuid4().hex
    slot_keys = [f"{GLOBAL_SLOT_PREFIX}:{index}" for index in range(MAX_RUNNING_TASKS)]

    with get_redis_init() as r:
        claim_first_free_slot = r.register_script(_CLAIM_FIRST_FREE_SLOT_SCRIPT)
        claimed_slot_key = claim_first_free_slot(keys=slot_keys, args=[owner_token, TASK_LOCK_TTL_SECONDS])

    return (claimed_slot_key, owner_token) if claimed_slot_key else (None, None)


def _bind_task_id_to_resource(task_id: str | None, map_key_prefix: str, resource_key: str, owner_token: str) -> None:
    if not task_id:
        redis_delete_if_value_matches(resource_key, owner_token)
        return

    redis_set(
        f"{map_key_prefix}:{task_id}",
        json.dumps({"resource_key": resource_key, "owner_token": owner_token}),
        ex=TASK_LOCK_TTL_SECONDS,
    )


def _release_task_resource_by_id(task_id: str | None, map_key_prefix: str) -> None:
    if not task_id:
        return

    map_key = f"{map_key_prefix}:{task_id}"
    mapped = redis_get(map_key)
    if mapped:
        resource = json.loads(mapped)
        redis_delete_if_value_matches(resource["resource_key"], resource["owner_token"])
    redis_delete(map_key)


def bind_task_id_to_slot(task_id: str | None, slot_key: str, owner_token: str) -> None:
    _bind_task_id_to_resource(task_id, TASK_SLOT_MAP_PREFIX, slot_key, owner_token)


def map_task_to_lock(task_id: str | None, lock_key: str, owner_token: str) -> None:
    _bind_task_id_to_resource(task_id, TASK_LOCK_MAP_PREFIX, lock_key, owner_token)


def release_execution_slot(task_id: str | None) -> None:
    _release_task_resource_by_id(task_id, TASK_SLOT_MAP_PREFIX)


def unlock_task_execution(task_id: str | None) -> None:
    _release_task_resource_by_id(task_id, TASK_LOCK_MAP_PREFIX)



class DynamicTrackingSource:

    def __init__(self, key: str, getter, setter):
        self.__task_metadata_key__ = key
        self._getter = getter
        self._setter = setter

    def get_last_enqueued_at(self):
        return self._getter()

    def set_last_enqueued_at(self, value):
        self._setter(value)


class RedisTrackingSource(DynamicTrackingSource):

    def __init__(self, key: str):

        super().__init__(
            key=key,
            getter=lambda: self._get(key),
            setter=lambda value: self._set(key, value),
        )

    @staticmethod
    def _get(key):
        redis_value = redis_get(key)

        if not redis_value:
            return None

        try:
            payload = json.loads(redis_value)

            if isinstance(payload, dict):
                return payload.get("last_enqueued_at")

        except Exception:
            return redis_value

    @staticmethod
    def _set(key, value):
        redis_set(
            key,
            json.dumps({
                "last_enqueued_at": value
            })
        )

class TaskScheduler:

    @staticmethod
    def _cron_field_count(cron_expression: str) -> int:
        return len(cron_expression.split())

    @staticmethod
    def _normalize_for_cron(cron_expression: str, dt: datetime) -> datetime:
        # 6-field cron expressions include seconds; 5-field expressions are minute-granular.
        if TaskScheduler._cron_field_count(cron_expression) >= 6:
            return dt.astimezone(UTC).replace(microsecond=0)
        return dt.astimezone(UTC).replace(second=0, microsecond=0)

    @staticmethod
    def _ensure_celery_task(task: CeleryTask) -> None:
        if not hasattr(task, "apply_async"):
            raise TypeError("Expected a Celery task with .apply_async()")

    @staticmethod
    def _ensure_tracked_function(func: TrackedFunction) -> None:
        required_attrs = (
            "__task_metadata_key__",
            "get_last_enqueued_at",
            "set_last_enqueued_at",
        )

        if not all(hasattr(func, attr) for attr in required_attrs):
            raise TypeError("Function must expose enqueue tracking accessors")

    @staticmethod
    def _resolve_tracking_source(task: CeleryTask, tracking_source: TrackedFunction | None) -> TrackedFunction:

        if tracking_source is not None:
            TaskScheduler._ensure_tracked_function(tracking_source)
            return tracking_source

        if all(hasattr(task, attr) for attr in ("__task_metadata_key__", "get_last_enqueued_at", "set_last_enqueued_at")):
            return task

        task_run = getattr(task, "run", None)

        if task_run and all(hasattr(task_run, attr) for attr in ("__task_metadata_key__", "get_last_enqueued_at", "set_last_enqueued_at")):
            return task_run

        raise TypeError("Function must expose enqueue tracking accessors")

    @staticmethod
    def _tracking_key(tracking_source: TrackedFunction) -> str:
        return getattr(tracking_source, "__task_metadata_key__", "unknown")

    @staticmethod
    def _task_lock_key(tracking_key: str, task: CeleryTask) -> str:
        task_name = getattr(task, "name", "unknown")
        return build_task_lock_key(task_name, tracking_key)

    @staticmethod
    def try_lock_task(lock_key: str) -> str | None:
        owner_token = uuid.uuid4().hex
        acquired = redis_set_nx(lock_key, owner_token, ttl_seconds=TASK_LOCK_TTL_SECONDS)
        return owner_token if acquired else None

    @staticmethod
    def unlock_task(lock_key: str, owner_token: str) -> None:
        redis_delete_if_value_matches(lock_key, owner_token)

    @staticmethod
    def _to_utc(dt: str | datetime) -> datetime:

        if isinstance(dt, str):
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)

        return dt.astimezone(UTC)

    @staticmethod
    def _latest_cron_occurrence(cron_expression: str, now: datetime) -> datetime:

        now_point = TaskScheduler._normalize_for_cron(cron_expression, now)
        has_seconds = TaskScheduler._cron_field_count(cron_expression) >= 6

        if croniter.match(cron_expression, now_point, second_at_beginning=has_seconds):
            return now_point

        occurrence = croniter(cron_expression, now_point, second_at_beginning=has_seconds).get_prev(datetime)

        if occurrence.tzinfo is None:
            occurrence = occurrence.replace(tzinfo=UTC)

        return TaskScheduler._normalize_for_cron(cron_expression, occurrence)

    @staticmethod
    def _should_run_cron(last_enqueued_at: str | datetime | None, cron_expression: str) -> bool:

        now = TaskScheduler._normalize_for_cron(cron_expression, datetime.now(UTC))

        latest_occurrence = TaskScheduler._latest_cron_occurrence(cron_expression, now)

        if not last_enqueued_at:
            Logger.info("[cron.trigger] No last enqueue timestamp found; task is due")
            return True

        last_enqueued_at_dt = TaskScheduler._to_utc(last_enqueued_at)

        return last_enqueued_at_dt < latest_occurrence
    
    @staticmethod
    def _enqueue(task: CeleryTask, args: tuple[Any, ...] | None, kwargs: dict[str, Any] | None, task_id: str) -> Any:
        return task.apply_async(args=args or (), kwargs=kwargs or {}, task_id=task_id)

    @staticmethod
    def _parse_interval_seconds(interval_seconds: str | int | float) -> float:
        try:
            seconds = float(interval_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid interval_seconds: {interval_seconds}") from exc

        if seconds <= 0:
            raise ValueError(f"interval_seconds must be > 0, got {interval_seconds}")

        return seconds

    @staticmethod
    def _should_run_interval(last_enqueued_at: str | datetime | None, interval_seconds: str | int | float) -> bool:
        now = datetime.now(UTC)
        seconds = TaskScheduler._parse_interval_seconds(interval_seconds)

        if not last_enqueued_at:
            Logger.info("[cron.trigger] No last enqueue timestamp found; task is due")
            return True

        last_enqueued_at_dt = TaskScheduler._to_utc(last_enqueued_at)
        elapsed = (now - last_enqueued_at_dt).total_seconds()

        return elapsed >= seconds

    @staticmethod
    def _acquire_lock_and_slot_or_skip(key: str, task: CeleryTask) -> tuple[str, str, str, str] | None:
        lock_key = TaskScheduler._task_lock_key(key, task)
        owner_token = TaskScheduler.try_lock_task(lock_key)
        if owner_token is None:
            Logger.warning(
                f"[cron.trigger] SKIPPED task={getattr(task, 'name', 'unknown')} "
                f"key={key} reason=task_already_locked ttl={TASK_LOCK_TTL_SECONDS}s"
            )
            return None

        slot_key, slot_token = reserve_task_slot()
        if slot_key is None:
            Logger.warning(
                f"[cron.trigger] SKIPPED task={getattr(task, 'name', 'unknown')} "
                f"key={key} reason=max_running_tasks_reached max={MAX_RUNNING_TASKS}"
            )
            TaskScheduler.unlock_task(lock_key, owner_token)
            return None

        return lock_key, owner_token, slot_key, slot_token

    @staticmethod
    def _release_claimed_resources(lock_key: str, owner_token: str, slot_key: str, slot_token: str) -> None:
        redis_delete_if_value_matches(slot_key, slot_token)
        TaskScheduler.unlock_task(lock_key, owner_token)

    @staticmethod
    def _try_enqueue(
        key: str,
        task: CeleryTask,
        tracking_source: TrackedFunction,
        args: tuple[Any, ...] | None,
        kwargs: dict[str, Any] | None,
        schedule_description: str,
    ) -> bool:
        claimed = TaskScheduler._acquire_lock_and_slot_or_skip(key, task)
        if claimed is None:
            return False
        lock_key, owner_token, slot_key, slot_token = claimed

        task_id = uuid.uuid4().hex
        bind_task_id_to_slot(task_id, slot_key, slot_token)
        map_task_to_lock(task_id, lock_key, owner_token)

        try:
            async_result = TaskScheduler._enqueue(task, args, kwargs, task_id)
        except Exception:
            release_execution_slot(task_id)
            unlock_task_execution(task_id)
            TaskScheduler._release_claimed_resources(lock_key, owner_token, slot_key, slot_token)
            raise

        if async_result is None:
            release_execution_slot(task_id)
            unlock_task_execution(task_id)
            TaskScheduler._release_claimed_resources(lock_key, owner_token, slot_key, slot_token)
            return False

        tracking_source.set_last_enqueued_at(datetime.now(UTC).isoformat())

        Logger.success(
            f"[cron.trigger] ENQUEUED "
            f"task={getattr(task, 'name', 'unknown')} "
            f"key={key} "
            f"{schedule_description} "
            f"task_id={task_id} "
            f"slot={slot_key} "
            f"task_lock_ttl={TASK_LOCK_TTL_SECONDS}s"
        )

        return True

    @staticmethod
    def run_if_due_interval(
        interval_seconds: str | int | float,
        task: CeleryTask,
        tracking_source: TrackedFunction | None = None,
        args: tuple[Any, ...] | None = None,
        kwargs: dict[str, Any] | None = None,
        force: bool = False,
    ) -> bool:

        TaskScheduler._ensure_celery_task(task)

        tracking_source = TaskScheduler._resolve_tracking_source(task, tracking_source)

        key = TaskScheduler._tracking_key(tracking_source)

        last_enqueued_at = tracking_source.get_last_enqueued_at()

        is_due = force or TaskScheduler._should_run_interval(last_enqueued_at, interval_seconds)

        if not is_due:
            return False

        return TaskScheduler._try_enqueue(
            key, task, tracking_source, args, kwargs,
            schedule_description=f"interval_seconds={interval_seconds}" + (" force=True" if force else ""),
        )

    @staticmethod
    def run_if_due(
        interval_seconds: str | int | float,
        task: CeleryTask,
        tracking_source: TrackedFunction | None = None,
        args: tuple[Any, ...] | None = None,
        kwargs: dict[str, Any] | None = None,
        force: bool = False,
    ) -> bool:
        return TaskScheduler.run_if_due_interval(
            interval_seconds=interval_seconds,
            task=task,
            tracking_source=tracking_source,
            args=args,
            kwargs=kwargs,
            force=force,
        )

    @staticmethod
    def run_if_due_cron(
        cron_expression: str,
        task: CeleryTask,
        tracking_key : str | None = None,
        tracking_source: TrackedFunction | None = None,
        args: tuple[Any, ...] | None = None,
        kwargs: dict[str, Any] | None = None,
        force: bool = False,
    ) -> bool:

        if tracking_source is None and tracking_key:
            tracking_source = RedisTrackingSource(tracking_key)
        elif tracking_source is not None and tracking_key is not None:
            raise ValueError("Cannot specify both tracking_source and tracking_key")

        TaskScheduler._ensure_celery_task(task)

        tracking_source = TaskScheduler._resolve_tracking_source(task, tracking_source)

        key = TaskScheduler._tracking_key(tracking_source)

        last_enqueued_at = tracking_source.get_last_enqueued_at()

        is_due = force or TaskScheduler._should_run_cron(last_enqueued_at, cron_expression)

        if not is_due:
            return False

        return TaskScheduler._try_enqueue(
            key, task, tracking_source, args, kwargs,
            schedule_description=f"cron={cron_expression}" + (" force=True" if force else ""),
        )


Scheduler = TaskScheduler


