from datetime import date as date_cls, datetime, time, timedelta, timezone

from sqlalchemy import func

from apps.app.modules.task.entities.task_run_entity import TaskRunEntity, TaskRunStatusEnum
from apps.app.utils.datetime import DateTime
from database.session_factory import get_session

MAX_TREND_DAYS = 30

TREND_STATUSES = (TaskRunStatusEnum.SUCCESS, TaskRunStatusEnum.FAILED, TaskRunStatusEnum.INTERRUPTED)


def get_task_run_daily_trend(days: int = 30) -> dict:
    days = max(1, min(days, MAX_TREND_DAYS))

    user_dt = DateTime(None)
    start_date, start, end = user_dt.day_window(days)

    day_expr = func.date(TaskRunEntity.created_at)

    with get_session()() as session:
        rows = (
            session.query(
                day_expr.label("day"),
                TaskRunEntity.status,
                func.count(TaskRunEntity.id).label("count"),
            )
            .filter(TaskRunEntity.created_at >= start)
            .filter(TaskRunEntity.created_at < end)
            .filter(TaskRunEntity.status.in_(TREND_STATUSES))
            .group_by(day_expr, TaskRunEntity.status)
            .all()
        )

    counts_by_day: dict = {}
    for row in rows:
        counts_by_day.setdefault(row.day, {})[row.status.value] = row.count

    series = []
    for offset in range(days):
        current_day = start_date + timedelta(days=offset)
        day_counts = counts_by_day.get(current_day, {})
        series.append({
            "date": current_day.strftime("%a, %b %d"),
            "iso_date": current_day.isoformat(),
            "success": day_counts.get(TaskRunStatusEnum.SUCCESS.value, 0),
            "failed": day_counts.get(TaskRunStatusEnum.FAILED.value, 0),
            "interrupted": day_counts.get(TaskRunStatusEnum.INTERRUPTED.value, 0),
        })

    return {"days": days, "series": series}


UNNAMED_ANALYSIS_LABEL = "Unnamed analysis"


def get_task_run_daily_breakdown(iso_date: str) -> dict:
    try:
        parsed_date = date_cls.fromisoformat(iso_date)
    except ValueError:
        raise ValueError(f"Invalid date '{iso_date}', expected YYYY-MM-DD")

    start = datetime.combine(parsed_date, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    with get_session()() as session:
        rows = (
            session.query(
                TaskRunEntity.name,
                TaskRunEntity.status,
                func.count(TaskRunEntity.id).label("count"),
            )
            .filter(TaskRunEntity.created_at >= start)
            .filter(TaskRunEntity.created_at < end)
            .filter(TaskRunEntity.status.in_(TREND_STATUSES))
            .group_by(TaskRunEntity.name, TaskRunEntity.status)
            .all()
        )

    counts_by_name: dict = {}
    for row in rows:
        label = row.name or UNNAMED_ANALYSIS_LABEL
        counts_by_name.setdefault(label, {})[row.status.value] = row.count

    tasks = [
        {
            "name": name,
            "success": counts.get(TaskRunStatusEnum.SUCCESS.value, 0),
            "failed": counts.get(TaskRunStatusEnum.FAILED.value, 0),
            "interrupted": counts.get(TaskRunStatusEnum.INTERRUPTED.value, 0),
        }
        for name, counts in counts_by_name.items()
    ]
    tasks.sort(key=lambda t: t["name"])

    return {"iso_date": iso_date, "tasks": tasks}


def get_task_run_daily_status_runs(iso_date: str, name: str, status: str) -> dict:
    try:
        parsed_date = date_cls.fromisoformat(iso_date)
    except ValueError:
        raise ValueError(f"Invalid date '{iso_date}', expected YYYY-MM-DD")

    valid_statuses = {s.value for s in TREND_STATUSES}
    if status not in valid_statuses:
        raise ValueError(f"Invalid status '{status}', expected one of {sorted(valid_statuses)}")

    start = datetime.combine(parsed_date, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)

    name_filter = (
        TaskRunEntity.name.is_(None) if name == UNNAMED_ANALYSIS_LABEL else TaskRunEntity.name == name
    )

    with get_session()() as session:
        rows = (
            session.query(TaskRunEntity)
            .filter(TaskRunEntity.created_at >= start)
            .filter(TaskRunEntity.created_at < end)
            .filter(TaskRunEntity.status == status)
            .filter(name_filter)
            .order_by(TaskRunEntity.created_at.desc())
            .all()
        )

        runs = [
            {
                "task_id": str(row.id),
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            }
            for row in rows
        ]

    return {"iso_date": iso_date, "name": name, "status": status, "runs": runs}
