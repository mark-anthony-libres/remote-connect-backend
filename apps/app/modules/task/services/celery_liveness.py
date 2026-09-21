from apps.app.utils.logger import Logger


def get_live_celery_task_ids(timeout: float = 2.0) -> set[str] | None:
    from apps.app.celery_app import celery_app

    try:
        inspector = celery_app.control.inspect(timeout=timeout)
        active = inspector.active()
        reserved = inspector.reserved()
    except Exception as exc:
        Logger.warning(f"[celery.liveness] Failed to inspect Celery workers: {exc}")
        return None

    if active is None and reserved is None:
        return None

    live_ids: set[str] = set()
    for worker_tasks in (active or {}).values():
        for entry in worker_tasks:
            task_id = entry.get("id")
            if task_id:
                live_ids.add(str(task_id))
    for worker_tasks in (reserved or {}).values():
        for entry in worker_tasks:
            task_id = entry.get("id")
            if task_id:
                live_ids.add(str(task_id))

    return live_ids


def is_task_id_live(task_id, timeout: float = 2.0) -> bool:
    live_ids = get_live_celery_task_ids(timeout=timeout)
    if live_ids is None:
        return False
    return str(task_id) in live_ids
