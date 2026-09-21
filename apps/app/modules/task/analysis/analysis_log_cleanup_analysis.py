from datetime import datetime, timedelta, timezone
from typing import Optional
import os

from botocore.exceptions import BotoCoreError, ClientError

from apps.app.core.settings import settings
from apps.app.modules.task.repositories.task_run_repository import TaskRunRepository
from apps.app.utils.analysis_run_logger import analysis_log_path, analysis_logs_dir
from apps.app.utils.decorators.analysis import analysis
from apps.app.utils.log_redaction import redact_log_content
from apps.app.utils.logger import Logger
from apps.app.utils.s3 import get_s3_client, is_s3_configured, s3_object_url
from database.session_factory import get_session


def _retention_cutoff(reference_time: datetime, retention_seconds: int) -> datetime:
    return reference_time - timedelta(seconds=retention_seconds)


def _archive_analysis_log_to_s3(s3_client, task_id: str, file_path: str) -> Optional[dict]:
    bucket = settings.s3_bucket_name
    s3_key = f"{settings.analysis_log_s3_prefix}/{task_id}.log"

    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            redacted_content = redact_log_content(f.read())
    except OSError as exc:
        Logger.warning(f"[analysis_log_cleanup] Failed to read analysis log {task_id} for archival: {exc}")
        return None

    try:
        s3_client.put_object(
            Bucket=bucket,
            Key=s3_key,
            Body=redacted_content.encode("utf-8"),
            ContentType="text/plain",
        )
    except (BotoCoreError, ClientError) as exc:
        Logger.warning(f"[analysis_log_cleanup] Failed to archive/upload analysis log {task_id} to S3: {exc}")
        return None

    return {
        "s3_bucket": bucket,
        "s3_log_path": s3_key,
        "s3_log_url": s3_object_url(bucket, s3_key),
    }


@analysis(cron="0 0 4 * * *", name="Archive local analysis log files to S3")
def cleanup_old_analysis_logs():
    if not is_s3_configured():
        Logger.warning("[analysis_log_cleanup] S3 archival not configured, skipping cleanup")
        return

    logs_dir = analysis_logs_dir()
    if not os.path.isdir(logs_dir):
        return

    retention_seconds = settings.analysis_log_retention_seconds
    archive_cutoff = _retention_cutoff(datetime.now(timezone.utc), retention_seconds)

    with get_session()() as session:
        expired_task_ids = TaskRunRepository(session).get_log_ids_older_than(archive_cutoff)

    s3_client = get_s3_client()

    archived_count = 0
    for task_id in expired_task_ids:
        file_path = analysis_log_path(task_id)
        if not os.path.isfile(file_path):
            continue

        s3_archive_info = _archive_analysis_log_to_s3(s3_client, task_id, file_path)
        if not s3_archive_info:
            continue

        with get_session()() as session:
            TaskRunRepository(session).set_log_archived(
                task_id,
                s3_archive_info["s3_bucket"],
                s3_archive_info["s3_log_path"],
                s3_archive_info["s3_log_url"],
            )

        os.remove(file_path)
        archived_count += 1

    Logger.info(
        f"[analysis_log_cleanup] Archived to S3 and deleted {archived_count} analysis log file(s) "
        f"for analysis runs older than {retention_seconds} seconds"
    )
