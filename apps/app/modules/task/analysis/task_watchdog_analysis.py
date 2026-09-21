from datetime import datetime, timedelta, timezone

from celery import current_task

from apps.app.core.settings import settings
from apps.app.modules.task.repositories.task_run_repository import TaskRunRepository
from apps.app.modules.task.services.celery_liveness import get_live_celery_task_ids
from apps.app.utils.decorators.analysis import analysis
from apps.app.utils.logger import Logger
from apps.app.utils.task_concurrency import release_execution_slot, unlock_task_execution
from apps.monitor.websocket.emitter import invalidate_group_sync
from database.session_factory import get_session


def _current_task_id() -> str | None:
    request = getattr(current_task, "request", None)
    task_id = getattr(request, "id", None)
    return str(task_id) if task_id else None


@analysis(interval={"minutes": 10}, name="Detect and mark abandoned task runs")
def detect_abandoned_task_runs():
    live_task_ids = get_live_celery_task_ids()

    if live_task_ids is None:
        Logger.warning(
            "[task_watchdog] Could not reach any Celery workers to check task "
            "liveness - skipping this run rather than risk marking active tasks interrupted."
        )
        return

    self_task_id = _current_task_id()
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=settings.task_watchdog_grace_period_seconds
    )

    with get_session()() as session:
        repo = TaskRunRepository(session)
        candidates = repo.get_stale_queued_or_running(older_than=cutoff)

        interrupted_ids = []
        for task_run in candidates:
    
            task_id = task_run.id.hex

            if task_id == self_task_id:
                continue

            if task_id in live_task_ids:
                continue

            repo.mark_interrupted(
                task_id,
                reason=(
                    "Task abandoned: worker process no longer reports it as "
                    "active or reserved (likely crashed mid-run)"
                ),
            )
           
            release_execution_slot(task_id)
            unlock_task_execution(task_id)
            interrupted_ids.append(task_id)

    if interrupted_ids:
        invalidate_group_sync("monitor")
        Logger.warning(
            f"[task_watchdog] Marked {len(interrupted_ids)} abandoned task run(s) "
            f"as interrupted and released their pool slots/locks: {', '.join(interrupted_ids)}"
        )
    else:
        Logger.info("[task_watchdog] No abandoned task runs found")
