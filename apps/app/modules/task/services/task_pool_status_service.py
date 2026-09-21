import json
from datetime import datetime, timezone

from apps.app.modules.task.repositories.task_run_repository import TaskRunRepository
from apps.app.utils.redis import get_redis_init
from apps.app.utils.task_concurrency import (
    GLOBAL_SLOT_PREFIX,
    MAX_RUNNING_TASKS,
    TASK_LOCK_TTL_SECONDS,
    TASK_SLOT_MAP_PREFIX,
)
from database.session_factory import SessionFactory

UTC = timezone.utc


def _slot_key_to_task_id(r, slot_keys: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for task_slot_key in r.scan_iter(match=f"{TASK_SLOT_MAP_PREFIX}:*"):
        raw = r.get(task_slot_key)
        if not raw:
            continue
        try:
            binding = json.loads(raw)
        except (TypeError, ValueError):
            continue
        resource_key = binding.get("resource_key")
        if resource_key not in slot_keys or resource_key in mapping:
            continue
        mapping[resource_key] = task_slot_key.split(":")[-1]
    return mapping


def get_task_pool_status(context=None) -> dict:
    slot_keys = [f"{GLOBAL_SLOT_PREFIX}:{index}" for index in range(MAX_RUNNING_TASKS)]

    with get_redis_init() as r:
        pipe = r.pipeline()
        for slot_key in slot_keys:
            pipe.get(slot_key)
            pipe.ttl(slot_key)
        owner_tokens_and_ttls = pipe.execute()

        slot_key_to_task_id = _slot_key_to_task_id(r, slot_keys)

    task_ids = list(slot_key_to_task_id.values())
    task_runs_by_id = {}
    if task_ids:
        if context is not None:
            for task_run in TaskRunRepository(context.session).get_by_task_ids(task_ids):
                task_runs_by_id[str(task_run.id).replace("-", "")] = task_run
        else:
            with SessionFactory() as session:
                for task_run in TaskRunRepository(session).get_by_task_ids(task_ids):
                    task_runs_by_id[str(task_run.id).replace("-", "")] = task_run

    now = datetime.now(UTC)
    slots = []
    available_count = 0

    for index, slot_key in enumerate(slot_keys):
        owner_token = owner_tokens_and_ttls[index * 2]
        ttl = owner_tokens_and_ttls[index * 2 + 1]

        if not owner_token:
            available_count += 1
            slots.append({"index": index, "state": "available"})
            continue

        task_id = slot_key_to_task_id.get(slot_key)
        task_run = task_runs_by_id.get(task_id) if task_id else None

        slot = {
            "index": index,
            "state": "occupied",
            "slot_ttl_seconds": ttl if ttl and ttl > 0 else None,
        }

        if task_run:
            status = getattr(task_run.status, "value", task_run.status)
            reference_time = task_run.started_at or task_run.created_at
            if reference_time and reference_time.tzinfo is None:
                reference_time = reference_time.replace(tzinfo=UTC)

            slot.update({
                "task_id": str(task_run.id),
                "task_name": task_run.task_name,
                "name": task_run.name,
                "tag": task_run.tag,
                "status": status,
                "started_at": task_run.started_at.isoformat() if task_run.started_at else None,
                "queued_at": task_run.created_at.isoformat() if task_run.created_at else None,
                "elapsed_seconds": (now - reference_time).total_seconds() if reference_time else None,
            })
        else:
            slot.update({
                "task_id": task_id,
                "note": "no matching task_run row - binding may have expired or been cleaned up",
            })

        slots.append(slot)

    return {
        "max_slots": MAX_RUNNING_TASKS,
        "in_use": MAX_RUNNING_TASKS - available_count,
        "available": available_count,
        "stale_timeout_seconds": TASK_LOCK_TTL_SECONDS,
        "generated_at": now.isoformat(),
        "slots": slots,
    }
