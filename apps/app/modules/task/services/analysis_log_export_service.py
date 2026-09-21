import os
import secrets
import tempfile
from datetime import datetime, timezone
from typing import Optional

from botocore.exceptions import BotoCoreError, ClientError

from apps.app.core.settings import settings
from apps.app.modules.task.repositories.task_run_repository import TaskRunRepository
from apps.app.utils.analysis_run_logger import analysis_log_path
from apps.app.utils.email import EmailUtil
from apps.app.utils.log_redaction import redact_log_content
from apps.app.utils.logger import Logger
from apps.app.utils.redis import redis_set
from apps.app.utils.s3 import get_s3_client, is_s3_configured
from apps.app.utils.zip_encryption import generate_zip_password, zip_and_encrypt

_TOKEN_REDIS_KEY_PREFIX = "analysis_log_export:token:"


def analysis_log_export_token_key(token: str) -> str:
    return f"{_TOKEN_REDIS_KEY_PREFIX}{token}"


class AnalysisLogExportError(Exception):
    pass


def _local_analysis_log_path(task_id: str) -> Optional[str]:
    path = analysis_log_path(task_id)
    return path if os.path.isfile(path) else None


def _download_archived_log(s3_client, bucket: str, s3_key: str, task_id: str) -> Optional[str]:
    fd, local_path = tempfile.mkstemp(suffix=f"-{task_id}.log")
    os.close(fd)
    try:
        s3_client.download_file(bucket, s3_key, local_path)
    except (BotoCoreError, ClientError) as exc:
        Logger.warning(f"[analysis_log_export] Failed to download archived log for task {task_id}: {exc}")
        os.remove(local_path)
        return None
    return local_path


def export_analysis_log_by_email(context, task_id: str, requested_by: Optional[str] = None) -> dict:
    if not is_s3_configured():
        raise AnalysisLogExportError("S3 archival is not configured (S3_BUCKET_NAME/AWS credentials missing)")

    task_run = TaskRunRepository(context.session).get_task(task_id)
    if not task_run:
        return {"exported": False, "reason": "No task run found for this task ID"}
    task_label = task_run.name or task_run.task_name
    log_s3_bucket = task_run.log_s3_bucket
    log_s3_path = task_run.log_s3_path

    s3_client = get_s3_client()

    local_path = _local_analysis_log_path(task_id)
    downloaded_path = None
    if not local_path:
        if not log_s3_path:
            return {"exported": False, "reason": "No log file found for this task run"}
        downloaded_path = _download_archived_log(s3_client, log_s3_bucket or settings.s3_bucket_name, log_s3_path, task_id)
        if not downloaded_path:
            return {"exported": False, "reason": "Log file could not be retrieved from S3"}

    source_path = local_path or downloaded_path
    password = generate_zip_password()

    try:
        with open(source_path, "r", encoding="utf-8", errors="replace") as f:
            redacted_content = redact_log_content(f.read())
        zip_path = zip_and_encrypt([(redacted_content.encode("utf-8"), f"{task_id}.log")], password)
    finally:
        if downloaded_path:
            os.remove(downloaded_path)

    try:
        zip_size_bytes = os.path.getsize(zip_path)
        bucket = settings.s3_bucket_name
        s3_key = f"{settings.analysis_log_export_s3_prefix}/{task_id}.zip"

        try:
            s3_client.upload_file(zip_path, bucket, s3_key)
        except (BotoCoreError, ClientError) as exc:
            raise AnalysisLogExportError(f"Failed to upload analysis log export to S3: {exc}") from exc
    finally:
        os.remove(zip_path)

    token = secrets.token_urlsafe(32)
    redis_set(analysis_log_export_token_key(token), s3_key, ex=settings.analysis_log_export_token_ttl_seconds)
    download_url = f"{settings.base_url.rstrip('/')}{settings.api_prefix}/analysis-logs/export/download?token={token}"

    generated_at = datetime.now(timezone.utc)

    html = EmailUtil.create_template("analysis_log_export_ready.html", {
        "taskId": task_id,
        "taskLabel": task_label or "Unnamed analysis",
        "zipSizeMb": round(zip_size_bytes / (1024 * 1024), 2),
        "downloadUrl": download_url,
        "expiresInMinutes": settings.analysis_log_export_token_ttl_seconds // 60,
        "requestedBy": requested_by or "unknown",
        "generatedAt": generated_at.strftime("%B %d, %Y at %I:%M:%S %p UTC"),
    })

    EmailUtil.send(
        to=settings.mail_default_to,
        subject=f"CentCom: Analysis Log Export Ready ({task_label or task_id})",
        html=html,
    )

    Logger.info(
        f"[analysis_log_export] Exported analysis log for task {task_id} "
        f"({zip_size_bytes / (1024 * 1024):.2f} MB) to S3 and emailed download link "
        f"(requested_by={requested_by})"
    )

    return {
        "exported": True,
        "task_id": task_id,
        "zip_size_bytes": zip_size_bytes,
        "expires_in_seconds": settings.analysis_log_export_token_ttl_seconds,
        "password": password,
    }
