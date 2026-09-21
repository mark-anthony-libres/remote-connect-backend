from fastapi import APIRouter, HTTPException
from fastapi.responses import RedirectResponse

from apps.app.core.auth.decorators import Public
from apps.app.core.errors import handle_route_errors
from apps.app.core.settings import settings
from apps.app.modules.task.services.analysis_log_export_service import analysis_log_export_token_key
from apps.app.utils.redis import redis_get
from apps.app.utils.s3 import get_s3_client, presigned_download_url

router = APIRouter(prefix="/analysis-logs")


@router.get("/export/download")
@Public()
@handle_route_errors(context="Error redeeming analysis log export link")
def download_analysis_log_export(token: str):
    s3_key = redis_get(analysis_log_export_token_key(token))
    if not s3_key:
        raise HTTPException(status_code=410, detail="This download link has expired.")

    s3_client = get_s3_client()
    download_url = presigned_download_url(
        s3_client, settings.s3_bucket_name, s3_key, settings.analysis_log_export_download_expires_in_seconds
    )
    if not download_url:
        raise HTTPException(status_code=500, detail="Failed to generate a download link.")

    return RedirectResponse(url=download_url)
