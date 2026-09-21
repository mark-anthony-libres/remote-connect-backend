from celery import Task
from celery.exceptions import Ignore
from datetime import UTC, datetime
from apps.app.utils.analysis_run_logger import analysis_run_context
from apps.app.utils.logger import Logger
from apps.app.modules.task.services.task_tracking_service import TaskTrackingService


TASK_METADATA_ATTRIBUTE_NAMES = (
    "__task_metadata_key__",
    "get_task_metadata",
    "get_last_enqueued_at",
    "set_last_enqueued_at",
)


class TaskExecutionLifecycle:
    def __init__(self, on_task_start=None, on_task_failure=None):
        self.on_task_start = on_task_start
        self.on_task_failure = on_task_failure

    def handle_task_start(self, task_instance, task_id, args, kwargs):
        if callable(self.on_task_start):
            self.on_task_start(
                task_id=task_id,
                args=args,
                kwargs=kwargs,
                task=task_instance,
            )

    def handle_task_failure(self, task_instance, exc, task_id, args, kwargs, einfo):
        Logger.error(
            f"[celery.task] Task failed id={task_id} "
            f"name={getattr(task_instance, 'name', None)} error={exc}"
        )

        if callable(self.on_task_failure):
            self.on_task_failure(
                exc=exc,
                task_id=task_id,
                args=args,
                kwargs=kwargs,
                einfo=einfo,
                task=task_instance,
            )


class LifecycleAwareCeleryTask(Task):
    lifecycle: TaskExecutionLifecycle | None = None
    redeliver: bool = False

    @property
    def _task_tracking_service(self):
        return TaskTrackingService()

    def __call__(self, *args, **kwargs):
        task_id = getattr(self.request, "id", None)
        if not task_id:
            return super().__call__(*args, **kwargs)
        with analysis_run_context(task_id):
            return super().__call__(*args, **kwargs)

    def apply_async(self, args=None, kwargs=None, **options):
        result = super().apply_async(args=args, kwargs=kwargs, **options)

        task_id = getattr(result, "id", None)
        if task_id:
            task_tag = getattr(self, "__task_tracking_tag__", None)
            self._task_tracking_service.on_task_enqueued(
                task_id=str(task_id),
                task_name=self.name,
                tag=task_tag,
                name=getattr(self, "_analysis_name", None),
            )

        if hasattr(self, "set_last_enqueued_at"):
            enqueued_at = datetime.now(UTC).isoformat()
            self.set_last_enqueued_at(enqueued_at)

        Logger.info(
            f"[celery.task] Task enqueued name={self.name} id={result.id}"
        )

        return result


    def before_start(self, task_id, args, kwargs):
        is_retry = (getattr(self.request, "retries", 0) or 0) > 0

        if self.redeliver:
            self._task_tracking_service.on_task_started(str(task_id), is_retry=is_retry)
        else:
            started = self._task_tracking_service.try_start(
                str(task_id),
                task_name=self.name,
                tag=getattr(self, "__task_tracking_tag__", None),
                name=getattr(self, "_analysis_name", None),
                is_retry=is_retry,
            )
            if not started:
                Logger.warning(
                    f"[celery.task] Skipping duplicate/redelivered execution "
                    f"id={task_id} name={self.name} - a task_run row for this "
                    f"exact task_id was already past QUEUED, meaning this is a "
                    f"second delivery of the same message, not a fresh dispatch."
                )
                raise Ignore()

        Logger.info(
            f"[celery.task] Task started id={task_id} name={self.name} retry={is_retry}"
        )
        if self.lifecycle:
            self.lifecycle.handle_task_start(self, task_id, args, kwargs)
        super().before_start(task_id, args, kwargs)

    def on_success(self, retval, task_id, args, kwargs):
        self._task_tracking_service.on_task_success(str(task_id))
        super().on_success(retval, task_id, args, kwargs)

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        self._task_tracking_service.on_task_failed(str(task_id), str(exc) if exc else None)
        if self.lifecycle:
            self.lifecycle.handle_task_failure(self, exc, task_id, args, kwargs, einfo)
        super().on_failure(exc, task_id, args, kwargs, einfo)

    def after_return(self, status, retval, task_id, args, kwargs, einfo):
        from apps.app.utils.task_concurrency import release_execution_slot, unlock_task_execution

        release_execution_slot(task_id)
        unlock_task_execution(task_id)

        super().after_return(status, retval, task_id, args, kwargs, einfo)


def attach_task_metadata(source_function, celery_task):
    for attr_name in TASK_METADATA_ATTRIBUTE_NAMES:
        if hasattr(source_function, attr_name):
            setattr(celery_task, attr_name, getattr(source_function, attr_name))


def build_task_base_class(base_task_class, lifecycle: TaskExecutionLifecycle, redeliver: bool):
    class CustomCeleryTask(LifecycleAwareCeleryTask, base_task_class):
        pass

    CustomCeleryTask.lifecycle = lifecycle
    CustomCeleryTask.redeliver = redeliver
    return CustomCeleryTask


class CeleryTaskFactory:
    def __init__(self, *, metadata_ttl: int = 86400, redeliver: bool = False, **task_options):
        self.metadata_ttl = metadata_ttl
        self.task_options = dict(task_options)
        self.task_tracking_tag = self.task_options.pop("tracking_tag", None)

        self.on_task_start = self.task_options.pop("on_start", None)
        self.on_task_failure = self.task_options.pop("on_failure", None)

        self.task_options["acks_late"] = redeliver
        self.redeliver = redeliver

    def __call__(self, target_function):
        from apps.app.celery_app import celery_app
        from apps.app.utils.decorators.task_metadata import TaskMetadata

        base_task_class = self.task_options.pop("base", Task)

        lifecycle = TaskExecutionLifecycle(
            on_task_start=self.on_task_start,
            on_task_failure=self.on_task_failure,
        )

        task_base_class = build_task_base_class(base_task_class, lifecycle, self.redeliver)

        metadata_wrapped_function = TaskMetadata(ttl_seconds=self.metadata_ttl)(target_function)

        celery_task = celery_app.task(
            base=task_base_class,
            **self.task_options,
        )(metadata_wrapped_function)

        attach_task_metadata(metadata_wrapped_function, celery_task)
        setattr(celery_task, "__task_tracking_tag__", self.task_tracking_tag)

        return celery_task


def task(*, metadata_ttl: int = 86400, redeliver: bool = False, **task_options):
    return CeleryTaskFactory(metadata_ttl=metadata_ttl, redeliver=redeliver, **task_options)