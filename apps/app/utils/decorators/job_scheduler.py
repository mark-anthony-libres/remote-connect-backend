import functools
import logging
import json
from pathlib import Path
import tempfile
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apps.app.utils.redis import redis_set, redis_get
from infra.redis_keys import cron_jobs_registry as CRON_JOBS_KEY


_CRON_JOB_REGISTRY = []
_INTERVAL_JOB_REGISTRY = []


class CronJobManager:
    def __init__(self):
        self.scheduler = None
        self.logger = logging.getLogger("cron.job_manager")
        logging.getLogger("apscheduler.executors.default").setLevel(logging.ERROR)
        logging.getLogger("apscheduler.scheduler").setLevel(logging.ERROR)

    def get_scheduler(self):
        if self.scheduler is None:
            self.scheduler = AsyncIOScheduler(timezone=ZoneInfo("UTC"))
            self.scheduler.start()
        return self.scheduler

    def update_cron_job_info(self, job_info):
        try:
            field = f"{job_info['function']}::{job_info['path']}"
            redis_set(f"{CRON_JOBS_KEY}::{field}", json.dumps(job_info))
        except Exception as e:
            self.logger.error(f"Failed to write cron job info to Redis: {e}")

    def cron_job(self, cron_expr: str, job_id: str = None, **kwargs):
        def decorator(func):
            _CRON_JOB_REGISTRY.append({
                "func": func,
                "cron_expr": cron_expr,
                "job_id": job_id,
                "kwargs": kwargs,
            })
            return func
        return decorator

    def interval_job(self, job_id: str = None, **interval_kwargs):
        def decorator(func):
            _INTERVAL_JOB_REGISTRY.append({
                "func": func,
                "job_id": job_id,
                "interval_kwargs": interval_kwargs,
            })
            return func
        return decorator

    def register_all_jobs(self):
        scheduler = self.get_scheduler()
        import datetime

        for job in _CRON_JOB_REGISTRY:
            func = job["func"]
            source_func = getattr(func, "__wrapped__", func)
            cron_expr = job["cron_expr"]
            job_id = job["job_id"]
            kwargs = dict(job["kwargs"])

            kwargs.setdefault("id", job_id or func.__name__)
            kwargs.setdefault("replace_existing", True)

            fields = cron_expr.split()
            if len(fields) == 6:
                trigger = CronTrigger(
                    second=fields[0],
                    minute=fields[1],
                    hour=fields[2],
                    day=fields[3],
                    month=fields[4],
                    day_of_week=fields[5],
                )
            else:
                trigger = CronTrigger.from_crontab(cron_expr)

            now = datetime.datetime.now()

            def format_time(dt):
                if dt is None:
                    return "Never"
                return dt.strftime("%B %d, %Y %I:%M:%S %p")

            last_run = format_time(now)
            next_run_dt = trigger.get_next_fire_time(None, now)
            next_run = format_time(next_run_dt)

            job_info = {
                "function": func.__name__,
                "cron_expr": cron_expr,
                "module": func.__module__,
                "path": str(Path(source_func.__code__.co_filename).resolve()),
                "last_run": last_run,
                "next_run": next_run,
            }

            self.update_cron_job_info(job_info)
            scheduler.add_job(func, trigger, **kwargs)
            self.logger.info(
                f"Registered cron job '{func.__name__}' with schedule '{cron_expr}' (runtime)"
            )

        for job in _INTERVAL_JOB_REGISTRY:
            func = job["func"]
            job_id = job["job_id"]
            interval_kwargs = dict(job["interval_kwargs"])

            ms = interval_kwargs.pop("milliseconds", 0)
            if ms:
                interval_kwargs["seconds"] = interval_kwargs.get("seconds", 0) + ms / 1000.0

            add_kwargs = {
                "id": job_id or func.__name__,
                "replace_existing": True,
                "coalesce": True,
            }
            trigger = IntervalTrigger(**interval_kwargs)
            scheduler.add_job(func, trigger, **add_kwargs)
            self.logger.info(
                f"Registered interval job '{func.__name__}' with interval {interval_kwargs} (runtime)"
            )


def get_cron_job_registry():
    return list(_CRON_JOB_REGISTRY)


def get_interval_job_registry():
    return list(_INTERVAL_JOB_REGISTRY)


cron_job_manager = CronJobManager()
cron_job = cron_job_manager.cron_job
interval_job = cron_job_manager.interval_job