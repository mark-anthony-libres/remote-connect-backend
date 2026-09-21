import os
import re
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from botocore.exceptions import BotoCoreError, ClientError

from apps.app.core.settings import settings
from apps.app.utils.email import EmailUtil
from apps.app.utils.file_reference import FileReferenceError, decrypt_file_reference, encrypt_file_reference
from apps.app.utils.log_redaction import redact_log_content
from apps.app.utils.logger import Logger
from apps.app.utils.redis import redis_set
from apps.app.utils.s3 import get_s3_client, is_s3_configured
from apps.app.utils.zip_encryption import generate_zip_password, zip_and_encrypt

_TOKEN_REDIS_KEY_PREFIX = "local_log_export:token:"
_LOG_FILENAME_PATTERN = re.compile(r"^api-centcom\.\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}\.part-\d+\.log$")


def local_log_export_token_key(token: str) -> str:
    return f"{_TOKEN_REDIS_KEY_PREFIX}{token}"


class LocalLogArchiveError(Exception):
    pass


def _local_logs_dir() -> str:
    return os.path.join(os.getcwd(), "logs")


def list_local_log_files() -> list[dict]:
    logs_dir = _local_logs_dir()
    if not os.path.isdir(logs_dir):
        return []

    entries = []
    for filename in os.listdir(logs_dir):
        file_path = os.path.join(logs_dir, filename)
        if not os.path.isfile(file_path) or not _LOG_FILENAME_PATTERN.match(filename):
            continue

        stat = os.stat(file_path)
        entries.append({
            "reference": encrypt_file_reference(filename),
            "modified_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            "size_bytes": stat.st_size,
            "_mtime": stat.st_mtime,
        })

    entries.sort(key=lambda entry: entry["_mtime"], reverse=True)
    for index, entry in enumerate(entries, start=1):
        entry["index"] = index
        del entry["_mtime"]

    return entries


def _resolve_filenames(references: list[str]) -> list[str]:
    filenames = []
    for reference in references:
        try:
            filename = decrypt_file_reference(reference)
        except FileReferenceError as exc:
            raise LocalLogArchiveError("One or more file references are invalid or expired") from exc

        if not _LOG_FILENAME_PATTERN.match(filename):
            raise LocalLogArchiveError("One or more file references are invalid")

        filenames.append(filename)

    return filenames


def request_local_log_download(references: list[str], requested_by: Optional[str] = None) -> dict:
    if not is_s3_configured():
        raise LocalLogArchiveError("S3 archival is not configured (S3_BUCKET_NAME/AWS credentials missing)")

    if not references:
        raise LocalLogArchiveError("No files were selected")

    filenames = _resolve_filenames(references)

    logs_dir = _local_logs_dir()
    file_paths = []
    for filename in filenames:
        file_path = os.path.join(logs_dir, filename)
        if not os.path.isfile(file_path):
            raise LocalLogArchiveError(
                "One or more selected files are no longer available - they may have just been archived"
            )
        file_paths.append(file_path)

    password = generate_zip_password()
    zip_files = []
    for index, path in enumerate(file_paths, start=1):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            redacted_content = redact_log_content(f.read())
        zip_files.append((redacted_content.encode("utf-8"), f"file-{index}.log"))
    zip_path = zip_and_encrypt(zip_files, password)

    try:
        file_size_bytes = os.path.getsize(zip_path)
        bucket = settings.s3_bucket_name
        s3_client = get_s3_client()
        s3_key = f"{settings.local_log_export_s3_prefix}/{uuid.uuid4().hex}.zip"

        try:
            s3_client.upload_file(zip_path, bucket, s3_key)
        except (BotoCoreError, ClientError) as exc:
            raise LocalLogArchiveError(f"Failed to upload the requested file(s) to S3: {exc}") from exc
    finally:
        os.remove(zip_path)

    token = secrets.token_urlsafe(32)
    redis_set(local_log_export_token_key(token), s3_key, ex=settings.local_log_export_token_ttl_seconds)
    download_url = f"{settings.base_url.rstrip('/')}{settings.api_prefix}/api-logs/archive/download?token={token}"

    generated_at = datetime.now(timezone.utc)

    html = EmailUtil.create_template("local_log_archive_ready.html", {
        "fileCount": len(file_paths),
        "zipSizeMb": round(file_size_bytes / (1024 * 1024), 2),
        "downloadUrl": download_url,
        "expiresInMinutes": settings.local_log_export_token_ttl_seconds // 60,
        "requestedBy": requested_by or "unknown",
        "generatedAt": generated_at.strftime("%B %d, %Y at %I:%M:%S %p UTC"),
    })

    EmailUtil.send(
        to=settings.mail_default_to,
        subject="CentCom: Archived Log File(s) Ready for Download",
        html=html,
    )

    Logger.info(
        f"[local_log_archive] Prepared {len(file_paths)} local log file(s) as a password-protected zip "
        f"({file_size_bytes / (1024 * 1024):.2f} MB) and emailed download link (requested_by={requested_by})"
    )

    return {
        "requested": True,
        "file_count": len(file_paths),
        "expires_in_seconds": settings.local_log_export_token_ttl_seconds,
        "password": password,
    }
