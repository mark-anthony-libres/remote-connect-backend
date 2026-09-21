from datetime import datetime, timedelta, timezone

from apps.app.core.settings import settings
from apps.app.utils.decorators.analysis import analysis
from apps.app.utils.logger import Logger
from apps.app.utils.s3 import is_s3_configured, purge_stale_objects


@analysis(interval={"minutes": 10}, name="Purge expired local log archive selections")
def purge_expired_local_log_archives():
    if not is_s3_configured():
        Logger.warning("[local_log_archive_cleanup] S3 not configured, skipping cleanup")
        return

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.local_log_export_token_ttl_seconds)
    purged_count = purge_stale_objects(
        settings.s3_bucket_name,
        f"{settings.local_log_export_s3_prefix}/",
        cutoff,
        "local_log_archive_cleanup",
    )

    if purged_count:
        Logger.info(f"[local_log_archive_cleanup] Purged {purged_count} stale local log archive selection(s) from S3")
