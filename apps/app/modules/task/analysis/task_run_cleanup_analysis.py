from datetime import datetime, timedelta, timezone

from botocore.exceptions import BotoCoreError, ClientError

from apps.app.core.settings import settings
from apps.app.modules.task.repositories.task_run_repository import TaskRunRepository
from apps.app.utils.decorators.analysis import analysis
from apps.app.utils.logger import Logger
from apps.app.utils.s3 import get_s3_client, is_s3_configured
from database.session_factory import get_session


def _retention_cutoff(reference_time: datetime, retention_seconds: int) -> datetime:
    return reference_time - timedelta(seconds=retention_seconds)


def _delete_analysis_log_from_s3(s3_client, task_id: str, bucket: str, s3_key: str) -> bool:
    try:
        s3_client.delete_object(Bucket=bucket, Key=s3_key)
        return True
    except (BotoCoreError, ClientError) as exc:
        Logger.warning(f"[analysis_log_purge] Failed to delete analysis log for task {task_id} ({bucket}/{s3_key}): {exc}")
        return False


@analysis(cron="0 45 2 * * *", name="Purge expired task run records")
def purge_expired_task_runs():
    retention_seconds = settings.task_run_retention_seconds
    cutoff = _retention_cutoff(datetime.now(timezone.utc), retention_seconds)

    with get_session()() as session:
        expired = TaskRunRepository(session).get_expired_task_runs(cutoff)

    if not expired:
        return

    s3_client = get_s3_client() if is_s3_configured() else None

    deleted_log_count = 0
    for task_id, bucket, s3_key in expired:
        if not s3_key:
            continue
        if not s3_client:
            Logger.warning(f"[analysis_log_purge] S3 not configured, skipping analysis log deletion for task {task_id}")
            continue
        if _delete_analysis_log_from_s3(s3_client, task_id, bucket, s3_key):
            deleted_log_count += 1

    with get_session()() as session:
        purged_count = TaskRunRepository(session).delete_by_ids([task_id for task_id, _, _ in expired])

    Logger.info(f"[task_run_purge] Permanently deleted {purged_count} task run(s) older than {retention_seconds} seconds")
    Logger.info(f"[analysis_log_purge] Deleted {deleted_log_count} analysis log archive(s) from S3 alongside the purged task runs")
