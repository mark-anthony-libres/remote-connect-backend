from apps.app.utils.logger import Logger


def get_worker_status(timeout: float = 2.0) -> dict:
    from apps.app.celery_app import celery_app

    try:
        inspector = celery_app.control.inspect(timeout=timeout)
        stats = inspector.stats()
    except Exception as exc:
        Logger.warning(f"[celery.liveness] Failed to inspect worker stats: {exc}")
        stats = None

    if stats is None:
        return {"reachable": False, "workers": []}

    workers = []
    for index, (worker_name, worker_stats) in enumerate(sorted(stats.items()), start=1):
        pool = (worker_stats or {}).get("pool") or {}
        workers.append({
            "name": f"worker-{index}",
            "concurrency": pool.get("max-concurrency"),
            "processes": len(pool.get("processes") or []),
        })

    return {"reachable": True, "workers": workers}
