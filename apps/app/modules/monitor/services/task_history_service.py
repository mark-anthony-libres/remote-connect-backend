from apps.app.modules.task.repositories.task_run_repository import TaskRunRepository
from database.session_factory import SessionFactory

DEFAULT_HISTORY_LIMIT = 50
MAX_HISTORY_LIMIT = 200


def get_task_run_history(limit: int = DEFAULT_HISTORY_LIMIT) -> dict:
    limit = max(1, min(limit, MAX_HISTORY_LIMIT))

    with SessionFactory() as session:
        task_runs = TaskRunRepository(session).get_recent_task_runs(limit=limit)

        runs = []
        for task_run in task_runs:
            status = getattr(task_run.status, "value", task_run.status)
            duration_seconds = None
            if task_run.started_at and task_run.finished_at:
                duration_seconds = (task_run.finished_at - task_run.started_at).total_seconds()

            runs.append({
                "task_id": str(task_run.id),
                "name": task_run.name,
                "tag": task_run.tag,
                "status": status,
                "is_retry": task_run.is_retry,
                "created_at": task_run.created_at.isoformat() if task_run.created_at else None,
                "started_at": task_run.started_at.isoformat() if task_run.started_at else None,
                "finished_at": task_run.finished_at.isoformat() if task_run.finished_at else None,
                "duration_seconds": duration_seconds,
                "has_error": bool(task_run.error),
            })

    return {"limit": limit, "runs": runs}
