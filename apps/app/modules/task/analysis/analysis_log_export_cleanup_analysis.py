from datetime import datetime, timedelta, timezone

from apps.app.core.settings import settings
from apps.app.utils.decorators.analysis import analysis
from apps.app.utils.logger import Logger
from apps.app.utils.s3 import is_s3_configured, purge_stale_objects


@analysis(interval={"minutes": 10}, name="Purge expired email-export analysis log temp files")
def purge_expired_analysis_log_exports():
    if not is_s3_configured():
        Logger.warning("[analysis_log_export_cleanup] S3 not configured, skipping cleanup")
        return

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=settings.analysis_log_export_token_ttl_seconds)
    purged_count = purge_stale_objects(
        settings.s3_bucket_name,
        f"{settings.analysis_log_export_s3_prefix}/",
        cutoff,
        "analysis_log_export_cleanup",
    )

    if purged_count:
        Logger.info(f"[analysis_log_export_cleanup] Purged {purged_count} stale email-export temp file(s) from S3")
