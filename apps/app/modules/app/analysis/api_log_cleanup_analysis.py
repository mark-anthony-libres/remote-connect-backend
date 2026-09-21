import os
import re
import tempfile
import zipfile
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from botocore.exceptions import BotoCoreError, ClientError

from apps.app.core.settings import settings
from apps.app.utils.decorators.analysis import analysis
from apps.app.utils.log_redaction import redact_log_content
from apps.app.utils.logger import Logger
from apps.app.utils.s3 import get_s3_client, is_s3_configured

_LOG_FILENAME_PATTERN = re.compile(r"^api-centcom\.\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.part-\d+\.log$")
_MONTH_DAY_YEAR_PATTERN = re.compile(r"^(\d{2})_(\d{2})_(\d{4})$")
_MONTH_DAY_YEAR_FORMAT = "%m_%d_%Y"


def _local_api_logs_dir() -> str:
    return os.path.join(os.getcwd(), "logs")


def _is_api_log_filename(filename: str) -> bool:
    return bool(_LOG_FILENAME_PATTERN.match(filename))


def _format_day_folder(day: date) -> str:
    return day.strftime(_MONTH_DAY_YEAR_FORMAT)


def _parse_day_folder(text: str) -> Optional[date]:
    match = _MONTH_DAY_YEAR_PATTERN.match(text)
    if not match:
        return None
    month, day, year = match.groups()
    return date(int(year), int(month), int(day))


def _grouped_archive_date(key: str) -> Optional[date]:
    basename = os.path.basename(key)
    if not basename.endswith(".zip"):
        return None
    return _parse_day_folder(basename[: -len(".zip")])


def _stale_cutoff_date(retention_seconds: int) -> date:
    return (datetime.now(timezone.utc) - timedelta(seconds=retention_seconds)).date()


def _iter_s3_objects(s3_client, bucket: str, prefix: str):
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        yield from page.get("Contents", [])


def _iter_s3_day_folders(s3_client, bucket: str, prefix: str):
    paginator = s3_client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix, Delimiter="/"):
        for common_prefix in page.get("CommonPrefixes", []):
            yield common_prefix["Prefix"]


@analysis(cron="0 15 * * * *", name="Archive local API log files to S3")
def archive_old_api_logs_to_s3():
    if not is_s3_configured():
        Logger.warning("[api_log_cleanup] S3 archival not configured, skipping cleanup")
        return

    logs_dir = _local_api_logs_dir()
    if not os.path.isdir(logs_dir):
        return

    retention_seconds = settings.api_log_retention_seconds
    stale_before_ts = datetime.now(timezone.utc).timestamp() - retention_seconds
    today_folder = _format_day_folder(datetime.now(timezone.utc).date())

    bucket = settings.s3_bucket_name
    s3_client = get_s3_client()

    archived_count = 0
    for filename in os.listdir(logs_dir):
        file_path = os.path.join(logs_dir, filename)
        if not os.path.isfile(file_path):
            continue

        if not _is_api_log_filename(filename) or os.path.getmtime(file_path) > stale_before_ts:
            continue

        s3_key = f"{settings.api_log_s3_prefix}/{today_folder}/{filename}"

        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                redacted_content = redact_log_content(f.read())
        except OSError as exc:
            Logger.warning(f"[api_log_cleanup] Failed to read {filename} for archival: {exc}")
            continue

        try:
            s3_client.put_object(
                Bucket=bucket,
                Key=s3_key,
                Body=redacted_content.encode("utf-8"),
                ContentType="text/plain",
            )
        except (BotoCoreError, ClientError) as exc:
            Logger.warning(f"[api_log_cleanup] Failed to upload {filename} to S3: {exc}")
            continue

        try:
            os.remove(file_path)
        except OSError as exc:
            Logger.warning(f"[api_log_cleanup] Uploaded {filename} but failed to delete local copy: {exc}")
            continue

        archived_count += 1

    Logger.info(
        f"[api_log_cleanup] Archived {archived_count} local api log file(s) to S3 "
        f"for files older than {retention_seconds} seconds"
    )


@analysis(cron="0 0 4 * * *", name="Group individual API log S3 archives into daily zips")
def group_old_api_log_archives_by_day():
    if not is_s3_configured():
        Logger.warning("[api_log_group] S3 archival not configured, skipping grouping")
        return

    bucket = settings.s3_bucket_name
    s3_client = get_s3_client()
    cutoff_date = _stale_cutoff_date(settings.api_log_s3_group_after_seconds)
    individual_prefix = f"{settings.api_log_s3_prefix}/"

    grouped_days = 0
    for day_prefix in _iter_s3_day_folders(s3_client, bucket, individual_prefix):
        day = _parse_day_folder(day_prefix[len(individual_prefix):].rstrip("/"))
        if day is None or day > cutoff_date:
            continue

        day_log_keys = [obj["Key"] for obj in _iter_s3_objects(s3_client, bucket, day_prefix)]
        if not day_log_keys:
            continue

        archive_key = f"{settings.api_log_s3_grouped_prefix}/{_format_day_folder(day)}.zip"

        with tempfile.TemporaryDirectory() as temp_dir:
            zip_path = os.path.join(temp_dir, os.path.basename(archive_key))

            try:
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
                    for key in day_log_keys:
                        local_path = os.path.join(temp_dir, os.path.basename(key))
                        s3_client.download_file(bucket, key, local_path)
                        zip_file.write(local_path, arcname=os.path.basename(key))
                        os.remove(local_path)

                s3_client.upload_file(zip_path, bucket, archive_key)
            except (BotoCoreError, ClientError, OSError) as exc:
                Logger.warning(f"[api_log_group] Failed to build/upload daily archive for {day}: {exc}")
                continue

        for key in day_log_keys:
            try:
                s3_client.delete_object(Bucket=bucket, Key=key)
            except (BotoCoreError, ClientError) as exc:
                Logger.warning(f"[api_log_group] Failed to delete source object {key} after grouping: {exc}")

        grouped_days += 1

    Logger.info(f"[api_log_group] Grouped api log archives into {grouped_days} daily zip file(s)")


@analysis(cron="0 15 4 * * *", name="Purge expired API log archives from S3")
def purge_expired_api_log_archives():
    if not is_s3_configured():
        Logger.warning("[api_log_purge] S3 archival not configured, skipping purge")
        return

    bucket = settings.s3_bucket_name
    s3_client = get_s3_client()
    cutoff_date = _stale_cutoff_date(settings.api_log_s3_retention_seconds)

    purged_count = 0
    for obj in _iter_s3_objects(s3_client, bucket, f"{settings.api_log_s3_grouped_prefix}/"):
        key = obj["Key"]
        archive_date = _grouped_archive_date(key)
        if archive_date is None or archive_date > cutoff_date:
            continue

        try:
            s3_client.delete_object(Bucket=bucket, Key=key)
            purged_count += 1
        except (BotoCoreError, ClientError) as exc:
            Logger.warning(f"[api_log_purge] Failed to delete {key}: {exc}")

    Logger.info(
        f"[api_log_purge] Permanently purged {purged_count} api log archive(s) "
        f"older than {settings.api_log_s3_retention_seconds} seconds"
    )
