import inspect
from functools import wraps

from apps.app.utils.decorators.job_scheduler import (
    cron_job,
    interval_job,
)
from apps.app.utils.decorators.task_decorator import task
from apps.app.utils.task_concurrency import Scheduler


def _interval_seconds(interval: dict) -> float:
    return (
        interval.get("weeks", 0) * 7 * 24 * 3600
        + interval.get("days", 0) * 24 * 3600
        + interval.get("hours", 0) * 3600
        + interval.get("minutes", 0) * 60
        + interval.get("seconds", 0)
        + interval.get("milliseconds", 0) / 1000
    )


def analysis(
    cron: str = None,
    interval: dict = None,
    name: str = None,
    direct: bool = False,
    redeliver: bool = False,
    **kwargs
):
   

    if not cron and not interval:
        raise ValueError(
            "analysis decorator requires "
            "'cron' or 'interval'"
        )

    if cron and interval:
        raise ValueError(
            "analysis decorator cannot use "
            "both cron and interval"
        )

    def decorator(func):

        job_id = func.__name__
        celery_task = None

        if direct:
            @wraps(func)
            def runner(force: bool = False):
                return func()
        else:
            
            first_param = next(iter(inspect.signature(func).parameters), None)
            celery_task = task(bind=first_param == "self", redeliver=redeliver)(func)
            
            celery_task._analysis_name = name

            @wraps(func)
            def runner(force: bool = False):
                if cron:
                    Scheduler.run_if_due_cron(cron_expression=cron, task=celery_task, force=force)
                else:
                    Scheduler.run_if_due(interval_seconds=_interval_seconds(interval), task=celery_task, force=force)

        wrapped = runner

        if cron:

            wrapped = cron_job(
                cron,
                job_id=job_id,
                **kwargs
            )(wrapped)

        elif interval:

            wrapped = interval_job(
                job_id=job_id,
                **interval,
                **kwargs
            )(wrapped)

        wrapped._is_analysis = True
        wrapped._analysis_job_id = job_id
        wrapped._analysis_name = name
        wrapped._celery_task = celery_task

        return wraps(func)(wrapped)

    return decorator
