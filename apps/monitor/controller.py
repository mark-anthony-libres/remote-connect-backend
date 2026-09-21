from datetime import datetime, timezone

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel

from apps.app.core import services
from apps.app.core.errors import handle_route_errors
from apps.app.modules.app.services.local_log_archive_service import (
    LocalLogArchiveError,
    list_local_log_files,
    request_local_log_download,
)
from apps.app.modules.task.services.analysis_log_export_service import (
    AnalysisLogExportError,
    export_analysis_log_by_email,
)
from apps.app.modules.task.services.task_pool_status_service import get_task_pool_status
from apps.app.modules.monitor.services.analysis_schedule_service import get_analysis_schedule_status
from apps.app.modules.monitor.services.monitor_session_service import redeem_session as redeem_monitor_session
from apps.app.modules.monitor.services.task_history_service import get_task_run_history
from apps.app.modules.monitor.services.task_run_trend_service import (
    get_task_run_daily_breakdown,
    get_task_run_daily_status_runs,
    get_task_run_daily_trend,
)
from apps.app.modules.monitor.services.monitor_access_guard import evaluate_monitor_access_request
from apps.app.modules.monitor.services.worker_status_service import get_worker_status
from apps.monitor.decorators import require_monitor_token

router = APIRouter(prefix="/monitor")


def _direct_client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/request-access")
@handle_route_errors(context="Error requesting monitor access")
def request_monitor_access(request: Request, x_access_key: str = Header(default=None)):
    return evaluate_monitor_access_request(ip=_direct_client_ip(request), access_key=x_access_key)


@router.post("/session")
@handle_route_errors(context="Error redeeming monitor session")
def redeem_session(x_monitor_token: str = Header(...)):
    result = redeem_monitor_session(x_monitor_token)
    if result is None:
        raise HTTPException(status_code=401, detail="Invalid, expired, or already-used monitor link")

    session_token, ttl_seconds = result
    return {"session_token": session_token, "expires_in_seconds": ttl_seconds}


@router.get("/pool")
@require_monitor_token
@handle_route_errors(context="Error fetching task pool status")
def get_pool_status(x_monitor_token: str = Header(...)):
    status = services.call(get_task_pool_status)
    for slot in status["slots"]:
        slot.pop("task_name", None)
    return status


@router.get("/workers")
@require_monitor_token
@handle_route_errors(context="Error fetching worker status")
def get_workers(x_monitor_token: str = Header(...)):
    return get_worker_status()


@router.get("/history")
@require_monitor_token
@handle_route_errors(context="Error fetching task history")
def get_history(x_monitor_token: str = Header(...), limit: int = Query(50, ge=1, le=200)):
    return get_task_run_history(limit=limit)


@router.get("/schedule")
@require_monitor_token
@handle_route_errors(context="Error fetching analysis schedule status")
def get_schedule(x_monitor_token: str = Header(...)):
    return get_analysis_schedule_status()


@router.get("/trend")
@require_monitor_token
@handle_route_errors(context="Error fetching task run trend")
def get_trend(x_monitor_token: str = Header(...), days: int = Query(30, ge=1, le=30)):
    return get_task_run_daily_trend(days=days)


@router.get("/trend/day")
@require_monitor_token
@handle_route_errors(context="Error fetching task run breakdown for the day")
def get_trend_day(
    x_monitor_token: str = Header(...),
    date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
):
    return get_task_run_daily_breakdown(iso_date=date)


@router.get("/trend/day/runs")
@require_monitor_token
@handle_route_errors(context="Error fetching task runs for the day")
def get_trend_day_runs(
    x_monitor_token: str = Header(...),
    date: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    name: str = Query(...),
    status: str = Query(..., pattern="^(success|failed|interrupted)$"),
):
    return get_task_run_daily_status_runs(iso_date=date, name=name, status=status)


@router.post("/task-runs/{task_id}/email-logs")
@require_monitor_token
@handle_route_errors(context="Error emailing analysis log to devs")
def email_task_run_logs(task_id: str, x_monitor_token: str = Header(...)):
    try:
        return services.call(export_analysis_log_by_email, task_id=task_id, requested_by="Task Monitor")
    except AnalysisLogExportError as exc:
        raise HTTPException(status_code=500, detail=str(exc))


class ArchiveDownloadRequest(BaseModel):
    references: list[str]


@router.get("/archive")
@require_monitor_token
@handle_route_errors(context="Error listing archived log files")
def get_archive_files(x_monitor_token: str = Header(...)):
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "files": list_local_log_files(),
    }


@router.post("/archive/download")
@require_monitor_token
@handle_route_errors(context="Error requesting archived log download")
def request_archive_download(body: ArchiveDownloadRequest, x_monitor_token: str = Header(...)):
    try:
        return request_local_log_download(references=body.references, requested_by="Monitor Archive")
    except LocalLogArchiveError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
