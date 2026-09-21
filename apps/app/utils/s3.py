import getpass
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from apps.app.core.settings import settings
from apps.app.utils.logger import Logger
from apps.app.utils import log_exception_with_traceback
from fastapi import UploadFile
import re


class S3NotConfiguredError(RuntimeError):
    pass


def upload_namespace() -> str:
    if settings.s3_key_namespace:
        return settings.s3_key_namespace
    try:
        user = getpass.getuser()
    except Exception:
        user = "unknown"
    return f"{settings.environment}-{user}"


def is_s3_configured() -> bool:
    return bool(settings.s3_bucket_name and settings.aws_access_key_id)


def get_s3_client():
    # Only pass explicit credentials when configured - passing empty strings
    # (rather than omitting the kwargs) makes boto3 use them literally instead
    # of falling back to its default chain (env vars, ~/.aws, IAM role).
    explicit_credentials = {}
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        explicit_credentials = {
            "aws_access_key_id": settings.aws_access_key_id,
            "aws_secret_access_key": settings.aws_secret_access_key,
        }

    return boto3.client(
        "s3",
        region_name=settings.aws_region,
        config=Config(signature_version="s3v4"),
        **explicit_credentials,
    )


def _configured_client():
    if not is_s3_configured():
        raise S3NotConfiguredError(
            "S3 is not configured. Set S3_BUCKET_NAME (and AWS_REGION) in .env."
        )
    return get_s3_client()


def s3_object_url(bucket: str, key: str) -> str:
    return f"https://{bucket}.s3.{settings.aws_region}.amazonaws.com/{key}"


def s3_object_exists(s3_client, bucket: str, key: str) -> bool:
    try:
        s3_client.head_object(Bucket=bucket, Key=key)
        return True
    except (BotoCoreError, ClientError):
        return False


def presigned_download_url(s3_client, bucket: str, key: str, expires_in: int) -> Optional[str]:
    try:
        return s3_client.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=expires_in,
        )
    except (BotoCoreError, ClientError) as exc:
        Logger.warning(f"[s3] Failed to generate download link for {bucket}/{key}: {exc}")
        return None


def purge_stale_objects(bucket: str, prefix: str, cutoff: datetime, log_context: str) -> int:
    s3_client = get_s3_client()
    purged_count = 0
    continuation_token = None

    while True:
        list_kwargs = {"Bucket": bucket, "Prefix": prefix}
        if continuation_token:
            list_kwargs["ContinuationToken"] = continuation_token

        try:
            response = s3_client.list_objects_v2(**list_kwargs)
        except (BotoCoreError, ClientError) as exc:
            Logger.warning(f"[{log_context}] Failed to list objects under {prefix}: {exc}")
            return purged_count

        for obj in response.get("Contents", []):
            if obj["LastModified"] >= cutoff:
                continue
            try:
                s3_client.delete_object(Bucket=bucket, Key=obj["Key"])
                purged_count += 1
            except (BotoCoreError, ClientError) as exc:
                Logger.warning(f"[{log_context}] Failed to delete stale object {obj['Key']}: {exc}")

        if not response.get("IsTruncated"):
            break
        continuation_token = response.get("NextContinuationToken")

    return purged_count


def build_object_key(filename: str, prefix: Optional[str] = None) -> str:
    clean_prefix = (prefix or settings.s3_attachment_prefix).strip("/")
    safe_name = Path(filename).name
    return f"{upload_namespace()}/{clean_prefix}/{uuid.uuid4().hex}-{safe_name}"


def upload_object(object_key: str, body: bytes, content_type: str) -> None:
    _configured_client().put_object(
        Bucket=settings.s3_bucket_name,
        Key=object_key,
        Body=body,
        ContentType=content_type,
    )


def head_object_size(object_key: str) -> int:
    head = _configured_client().head_object(Bucket=settings.s3_bucket_name, Key=object_key)
    return int(head.get("ContentLength") or 0)


def generate_download_url(
    object_key: str,
    file_name: str,
    expires_in: int = 300,
    disposition: str = "attachment",
) -> str:
    return _configured_client().generate_presigned_url(
        ClientMethod="get_object",
        Params={
            "Bucket": settings.s3_bucket_name,
            "Key": object_key,
            "ResponseContentDisposition": f'{disposition}; filename="{Path(file_name).name}"',
        },
        ExpiresIn=expires_in,
    )


def delete_object(object_key: str) -> None:
    _configured_client().delete_object(Bucket=settings.s3_bucket_name, Key=object_key)


def _sanitize_filename(filename: str) -> str:
  cleaned = re.sub(r"[^\w.\-]+", "_", filename or "attachment")
  return cleaned.strip("._") or "attachment"


def _feature_request_prefix() -> str:
  # Supports either "FEATURE-REQUEST-UPLOADS" or "bucket/FEATURE-REQUEST-UPLOADS"
  configured = (settings.aws_s3_feature_request_uploads or "FEATURE-REQUEST-UPLOADS").strip("/")
  if "/" in configured:
    _, prefix = configured.split("/", 1)
    return prefix.strip("/")
  return configured


class S3Util:
  @staticmethod
  def _client():
    return boto3.client(
      "s3",
      region_name=settings.aws_region,
      aws_access_key_id=settings.aws_access_key_id,
      aws_secret_access_key=settings.aws_secret_access_key,
    )

  @staticmethod
  async def upload_feature_request_file(file: UploadFile) -> dict[str, Any]:
    if not settings.aws_s3_bucket:
      raise Exception("AWS S3 bucket is not configured")
    if not file or not file.filename:
      raise Exception("Attachment file is required")

    content = await file.read()
    if not content:
      raise Exception("Attachment file is empty")

    filename = _sanitize_filename(file.filename)
    key = f"{upload_namespace()}/{_feature_request_prefix()}/{uuid.uuid4().hex}-{filename}"
    content_type = file.content_type or "application/octet-stream"

    try:
      S3Util._client().put_object(
        Bucket=settings.aws_s3_bucket,
        Key=key,
        Body=content,
        ContentType=content_type,
      )
    except (BotoCoreError, ClientError) as e:
      log_exception_with_traceback(e, context="Feature request S3 upload failed")
      raise Exception("Failed to upload attachment to S3") from e
    finally:
      await file.seek(0)

    url = f"https://{settings.aws_s3_bucket}.s3.{settings.aws_region}.amazonaws.com/{key}"

    return {
      "filename": file.filename,
      "stored_filename": filename,
      "content_type": content_type,
      "size": len(content),
      "key": key,
      "url": url,
    }

  @staticmethod
  def get_file_presigned_url(key: str, bucket: str | None = None) -> str:
    if not settings.aws_s3_bucket:
      raise Exception("AWS S3 bucket is not configured")
    if not key:
      raise Exception("Key is required")
    if not bucket:
      bucket = settings.aws_s3_bucket
    return S3Util._client().generate_presigned_url(
      "get_object",
      Params={
        "Bucket": bucket,
        "Key": key,
      },
      ExpiresIn=3600, # 1 hour
    )

