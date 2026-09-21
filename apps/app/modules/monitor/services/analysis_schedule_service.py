from datetime import datetime, timedelta, timezone

from cron_descriptor import get_description
from croniter import croniter

from apps.app.core.analysis_discovery import AnalysisJobDiscovery
from apps.app.utils.decorators.job_scheduler import get_cron_job_registry, get_interval_job_registry

UTC = timezone.utc


def _describe_interval(interval_kwargs: dict) -> str:
    interval_kwargs = dict(interval_kwargs)

    milliseconds = interval_kwargs.pop("milliseconds", 0)
    if milliseconds:
        interval_kwargs["seconds"] = interval_kwargs.get("seconds", 0) + milliseconds / 1000.0

    units = {"weeks": "week", "days": "day", "hours": "hour", "minutes": "minute", "seconds": "second"}

    parts = [
        f"{value:g} {label}{'s' if value != 1 else ''}"
        for key, label in units.items()
        if (value := interval_kwargs.get(key))
    ]

    return f"Every {', '.join(parts)}" if parts else "Every tick"


def _interval_total_seconds(interval_kwargs: dict) -> float:
    return (
        interval_kwargs.get("weeks", 0) * 7 * 24 * 3600
        + interval_kwargs.get("days", 0) * 24 * 3600
        + interval_kwargs.get("hours", 0) * 3600
        + interval_kwargs.get("minutes", 0) * 60
        + interval_kwargs.get("seconds", 0)
        + interval_kwargs.get("milliseconds", 0) / 1000
    )


def _next_cron_occurrence(cron_expr: str, now: datetime) -> datetime:
    has_seconds = len(cron_expr.split()) >= 6
    occurrence = croniter(cron_expr, now, second_at_beginning=has_seconds).get_next(datetime)
    if occurrence.tzinfo is None:
        occurrence = occurrence.replace(tzinfo=UTC)
    return occurrence


def _parse_iso(raw: str | None) -> datetime | None:
    if not raw:
        return None
    dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def get_analysis_schedule_status() -> dict:
    discovery = AnalysisJobDiscovery()
    discovery.import_analysis_modules()

    cron_by_func = {job["func"]: job["cron_expr"] for job in get_cron_job_registry()}
    interval_by_func = {job["func"]: job["interval_kwargs"] for job in get_interval_job_registry()}

    now = datetime.now(UTC)
    jobs = []

    for job in sorted(discovery.discover_analysis_jobs(), key=lambda j: j["job_id"]):
        func = job["function"]
        celery_task = getattr(func, "_celery_task", None)
        is_direct = celery_task is None

        cron_expr = cron_by_func.get(func)
        interval_kwargs = interval_by_func.get(func)

        last_triggered_at = None
        if celery_task is not None and hasattr(celery_task, "get_last_enqueued_at"):
            last_triggered_at = _parse_iso(celery_task.get_last_enqueued_at())

        schedule_type = "cron" if cron_expr else ("interval" if interval_kwargs else "unknown")
        schedule_description = "Unknown schedule"
        next_trigger_at = None

        if cron_expr:
            schedule_description = get_description(cron_expr)
            next_trigger_at = _next_cron_occurrence(cron_expr, now)
        elif interval_kwargs:
            schedule_description = _describe_interval(interval_kwargs)
            if last_triggered_at:
                next_trigger_at = last_triggered_at + timedelta(seconds=_interval_total_seconds(interval_kwargs))
            elif not is_direct:
                next_trigger_at = now

        seconds_until_next = None
        is_due = False
        if next_trigger_at:
            seconds_until_next = max(0, round((next_trigger_at - now).total_seconds()))
            is_due = next_trigger_at <= now

        jobs.append({
            "job_id": job["job_id"],
            "name": job.get("name"),
            "is_direct": is_direct,
            "schedule_type": schedule_type,
            "schedule_description": schedule_description,
            "last_triggered_at": last_triggered_at.isoformat() if last_triggered_at else None,
            "next_trigger_at": next_trigger_at.isoformat() if next_trigger_at else None,
            "seconds_until_next": seconds_until_next,
            "is_due": is_due,
        })

    return {
        "generated_at": now.isoformat(),
        "jobs": jobs,
    }
