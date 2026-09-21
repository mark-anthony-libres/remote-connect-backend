from apps.app.core.settings import settings
from apps.app.utils.decorators.analysis import analysis
from apps.app.utils.logger import Logger
from apps.app.modules.user.repositories.user_request_log_summary_repository import UserRequestLogSummaryRepository


@analysis(cron="0 0 0 * * *", name="Purge expired user request log summaries")
def cleanup_old_user_request_log_summaries():
    retention_days = settings.user_request_log_summary_retention_days
    deleted_count = UserRequestLogSummaryRepository().delete_older_than(retention_days)
    Logger.info(f"[user_request_log_summary_cleanup] Deleted {deleted_count} summary row(s) older than {retention_days} days")
