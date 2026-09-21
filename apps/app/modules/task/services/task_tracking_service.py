from apps.app.modules.task.repositories.task_run_repository import TaskRunRepository
from apps.app.utils.logger import Logger
from apps.monitor.websocket.emitter import invalidate_group_sync
from database import session_factory

MONITOR_GROUP = "monitor"


class TaskTrackingService:
    def on_task_enqueued(self, task_id: str, task_name: str, tag: str | None = None, name: str | None = None) -> None:
        try:
            with session_factory.SessionFactory() as db_session:
                repository = TaskRunRepository(db_session)
                repository.create_task_run(task_id=task_id, task_name=task_name, tag=tag, name=name)
            invalidate_group_sync(MONITOR_GROUP)
        except Exception as exc:
            Logger.warning(f"[task.tracking] enqueue tracking failed task_id={task_id} error={exc}")

    def on_task_started(self, task_id: str, is_retry: bool = False) -> None:
        try:
            with session_factory.SessionFactory() as db_session:
                repository = TaskRunRepository(db_session)
                repository.mark_running(task_id=task_id, is_retry=is_retry)
            invalidate_group_sync(MONITOR_GROUP)
        except Exception as exc:
            Logger.warning(f"[task.tracking] start tracking failed task_id={task_id} error={exc}")

    def try_start(
        self, task_id: str, task_name: str, tag: str | None, name: str | None = None, is_retry: bool = False
    ) -> bool:
        try:
            with session_factory.SessionFactory() as db_session:
                repository = TaskRunRepository(db_session)
                started = repository.try_start(
                    task_id=task_id, task_name=task_name, tag=tag, name=name, is_retry=is_retry
                )
            if started:
                invalidate_group_sync(MONITOR_GROUP)
            return started
        except Exception as exc:
            Logger.error(
                f"[task.tracking] Redelivery fencing check failed for task_id={task_id} - "
                f"cannot confirm this is not a duplicate delivery; proceeding anyway "
                f"rather than dropping the task: {exc}"
            )
            return True

    def on_task_success(self, task_id: str) -> None:
        try:
            with session_factory.SessionFactory() as db_session:
                repository = TaskRunRepository(db_session)
                repository.mark_success(task_id=task_id)
            invalidate_group_sync(MONITOR_GROUP)
        except Exception as exc:
            Logger.warning(f"[task.tracking] success tracking failed task_id={task_id} error={exc}")

    def on_task_failed(self, task_id: str, error: str | None) -> None:
        try:
            with session_factory.SessionFactory() as db_session:
                repository = TaskRunRepository(db_session)
                repository.mark_failed(task_id=task_id, error=error)
            invalidate_group_sync(MONITOR_GROUP)
        except Exception as exc:
            Logger.warning(f"[task.tracking] failure tracking failed task_id={task_id} error={exc}")
