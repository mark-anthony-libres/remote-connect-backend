

import os
import sys
import traceback

from cron_descriptor import get_description

from apps.app.utils.logger import Logger
from apps.app.core.analysis_discovery import AnalysisJobDiscovery
from apps.app.utils.decorators.job_scheduler import (
    get_cron_job_registry,
    get_interval_job_registry,
)
from apps.app.modules.task.services.task_pool_status_service import get_task_pool_status


def print_main_usage() -> None:
    Logger.info("Usage: python -m run.analysis <job id> [--task] [-f|--force]")
    Logger.info("Example: python -m run.analysis sync_analysis")
    Logger.info("  Runs the job's own body directly, in this process, right now.")
    Logger.info("  Pass --task to dispatch it the way a real scheduler tick would")
    Logger.info("  instead (through the Redis lock + Celery broker) - has no effect")
    Logger.info("  on direct=True jobs, which never go through that path either way.")
    Logger.info("  Add -f/--force (only with --task) to skip the 'is it due yet'")
    Logger.info("  schedule check and dispatch regardless - the dedup lock and pool")
    Logger.info("  slot limit still apply, so an already-running job or a full pool")
    Logger.info("  still won't double-dispatch.")
    Logger.info("Usage: python -m run.analysis explain [job id]")
    Logger.info("Example: python -m run.analysis explain cleanup_old_network_traffic")
    Logger.info("Usage: python -m run.analysis pool")
    Logger.info("  Shows every global concurrency slot (see task_concurrency.py):")
    Logger.info("  available, or occupied - and by which task, what its status is,")
    Logger.info("  and how long it's been queued/running.")


def describe_interval(interval_kwargs: dict) -> str:
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

    return f"Every {', '.join(parts)}" if parts else "Every interval tick"


def explain_analysis_jobs(job_id: str = None) -> None:
    analysis_service = AnalysisJobDiscovery()
    analysis_service.import_analysis_modules()

    cron_by_func = {job["func"]: job["cron_expr"] for job in get_cron_job_registry()}
    interval_by_func = {job["func"]: job["interval_kwargs"] for job in get_interval_job_registry()}

    all_jobs = sorted(analysis_service.discover_analysis_jobs(), key=lambda job: job["job_id"])
    jobs = [job for job in all_jobs if not job_id or job["job_id"] == job_id]

    if not jobs:
        if job_id:
            available = ", ".join(job["job_id"] for job in all_jobs)
            Logger.error(f"No analysis job found with id '{job_id}'. Available job ids: {available}")
        else:
            Logger.error("No analysis jobs were discovered.")
        return

    title = f"Registered analysis jobs ({len(jobs)})" if not job_id else "Registered analysis job"
    Logger.section(title)

    index_width = len(str(len(jobs)))

    for index, job in enumerate(jobs, start=1):
        func = job["function"]
        job_id = job["job_id"]
        display_name = job.get("name") or job_id

        cron_expr = cron_by_func.get(func)
        if cron_expr:
            schedule = get_description(cron_expr)
        elif func in interval_by_func:
            schedule = describe_interval(interval_by_func[func])
        else:
            schedule = "Unknown schedule"

        source_func = getattr(func, "__wrapped__", func)
        source_file = os.path.relpath(source_func.__code__.co_filename)
        source_line = source_func.__code__.co_firstlineno

        print(f"{Logger.BOLD}{Logger.CYAN}{index:>{index_width}}. {display_name}{Logger.RESET}")
        if display_name != job_id:
            print(f"{'':>{index_width}}    job id    {job_id}")
        print(f"{'':>{index_width}}    schedule  {Logger.GREEN}{schedule}{Logger.RESET}")
        if cron_expr:
            print(f"{'':>{index_width}}    cron      {cron_expr}")
        print(f"{'':>{index_width}}    source    {source_file}:{source_line}")
        print()


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))

    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def print_pool_status() -> None:
    pool = get_task_pool_status()
    index_width = len(str(pool["max_slots"]))

    Logger.section(f"Task pool ({pool['max_slots']} slots, stale timeout {pool['stale_timeout_seconds']}s)")

    for slot in pool["slots"]:
        label = f"{slot['index']:>{index_width}}"

        if slot["state"] == "available":
            print(f"{Logger.GREEN}{Logger.BOLD}[{label}] AVAILABLE{Logger.RESET}")
            print()
            continue

        print(f"{Logger.YELLOW}{Logger.BOLD}[{label}] OCCUPIED{Logger.RESET}")

        if slot.get("task_name"):
            print(f"{'':>{index_width}}    task_id      {slot['task_id']}")
            print(f"{'':>{index_width}}    task_name    {slot['task_name']}")
            if slot.get("tag"):
                print(f"{'':>{index_width}}    tag          {slot['tag']}")
            print(f"{'':>{index_width}}    status       {slot['status']}")

            if slot.get("started_at") or slot.get("queued_at"):
                verb = "started_at" if slot.get("started_at") else "queued_at"
                reference_time = slot.get("started_at") or slot.get("queued_at")
                print(f"{'':>{index_width}}    {verb:<10}   {reference_time}")
                print(f"{'':>{index_width}}    elapsed      {format_duration(slot['elapsed_seconds'])}")
        else:
            print(f"{'':>{index_width}}    task_id      {slot.get('task_id') or 'unknown'}")
            print(f"{'':>{index_width}}    note         {slot['note']}")

        ttl = slot.get("slot_ttl_seconds")
        ttl_display = f"{ttl}s" if ttl else "no expiry set"
        print(f"{'':>{index_width}}    slot_ttl     {ttl_display} (auto-freed if the worker dies without releasing it)")
        print()

    Logger.info(f"{pool['in_use']}/{pool['max_slots']} slots in use, {pool['available']} available")


def main():
    if len(sys.argv) < 2:
        print_main_usage()
        sys.exit(1)

    func_name = sys.argv[1]
    args = sys.argv[2:]

    if func_name == "explain":
        job_id = args[0] if args else None
        explain_analysis_jobs(job_id=job_id)
        return

    if func_name == "pool":
        print_pool_status()
        return

    via_task = "--task" in args
    force = "-f" in args or "--force" in args

    if force and not via_task:
        Logger.warning("-f/--force has no effect without --task - ignoring.")

    analysis_service = AnalysisJobDiscovery()

    try:
        if func_name == "all":
            analysis_service.run_all_analysis_jobs(via_task=via_task, force=force)
        else:
            analysis_service.run_analysis_job(func_name, via_task=via_task, force=force)
    except Exception as e:
        Logger.error("Analysis failed:\n" + traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
