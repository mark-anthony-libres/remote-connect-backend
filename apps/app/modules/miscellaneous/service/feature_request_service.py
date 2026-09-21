from datetime import datetime
import json

from apps.app.modules.app.repositories.app_configuration_repository import AppConfigurationRepository
from apps.app.modules.miscellaneous.entities.feature_request_entity import (
  FeatureRequest,
  FeatureRequestPriorityEnum,
  FeatureRequestStatusEnum,
)
from apps.app.modules.miscellaneous.repositories.feature_request_repository import FeatureRequestRepository
from apps.app.utils import log_exception_with_traceback
from apps.app.utils.email import EmailUtil
from apps.app.utils.s3 import S3Util
from database.session_factory import get_session


def _serialize_attachments(request_attachments) -> list[dict]:
  if not request_attachments or not isinstance(request_attachments, list):
    return []
  attachments = []
  for attachment in request_attachments:
    attachment = json.loads(attachment) if isinstance(attachment, str) else attachment
    attachment["url"] = S3Util.get_file_presigned_url(attachment["key"]) if attachment["key"] else None
    attachments.append(attachment)
  return attachments


def get_all_feature_requests() -> list[dict]:
  with get_session()() as session:
    feature_requests = FeatureRequestRepository(session).all()
    return [
      {
        "id": feature_request.id,
        "request_title": feature_request.request_title,
        "request_description": feature_request.request_description,
      }
      for feature_request in feature_requests
    ]


def get_paginated_feature_requests(
  context,
  page: int = 1,
  page_size: int = 10,
  keyword: str = "",
  sort_field: str = "request_title",
  sort_direction: str = "asc",
  request_status: str | None = None,
  request_priority: str | None = None,
  user_id: int | None = None,
) -> dict:
  if request_status and request_status not in ("null", "None", ""):
    if request_status not in FeatureRequestStatusEnum.__members__.values():
      raise Exception("Invalid request status")
    request_status = FeatureRequestStatusEnum(request_status)
  else:
    request_status = None

  if request_priority and request_priority not in ("null", "None", ""):
    if request_priority not in FeatureRequestPriorityEnum.__members__.values():
      raise Exception("Invalid request priority")
    request_priority = FeatureRequestPriorityEnum(request_priority)
  else:
    request_priority = None

  repository = FeatureRequestRepository(context.session)
  feature_requests, total = repository.get_paginated_feature_requests(
    page=page,
    page_size=page_size,
    keyword=keyword,
    sort_field=sort_field,
    sort_direction=sort_direction,
    request_status=request_status,
    request_priority=request_priority,
    user_id=user_id,
  )
  total_feature_requests_count = repository.total_count()
  total_pages = (
    total_feature_requests_count // page_size
    if total_feature_requests_count % page_size == 0
    else total_feature_requests_count // page_size + 1
  )
  return {
    "data": [
      {
        "id": feature_request.id,
        "request_id": feature_request.request_id,
        "request_title": feature_request.request_title,
        "request_description": feature_request.request_description,
        "request_status": feature_request.request_status,
        "request_priority": feature_request.request_priority,
        "request_email": feature_request.request_email,
        "request_business_impact": feature_request.request_business_impact,
        "request_attachments": _serialize_attachments(feature_request.request_attachments),
        "request_notes": feature_request.request_notes,
        "created_at": feature_request.created_at.isoformat() if feature_request.created_at else "",
        "updated_at": feature_request.updated_at.isoformat() if feature_request.updated_at else "",
        "created_by": feature_request.created_by.name if feature_request.created_by else "",
      }
      for feature_request in feature_requests
    ],
    "pagination": {
      "total": total,
      "page": page,
      "page_size": page_size,
      "total_pages": total_pages,
      "keyword": keyword,
      "sort_field": sort_field,
      "sort_direction": sort_direction,
    },
  }


def get_feature_request_by_id(context, feature_request_id: int) -> dict:
  feature_request = FeatureRequestRepository(context.session).get_by_id(feature_request_id)
  return {
    "id": feature_request.id,
    "request_id": feature_request.request_id,
    "request_title": feature_request.request_title,
    "request_description": feature_request.request_description,
    "request_status": feature_request.request_status,
    "request_priority": feature_request.request_priority,
    "request_email": feature_request.request_email,
    "request_business_impact": feature_request.request_business_impact,
    "request_attachments": _serialize_attachments(feature_request.request_attachments),
  }


def _send_feature_request_created_notification(session, feature_request: dict) -> None:
  try:
    recipient_config = AppConfigurationRepository(session).get_configuration_by_name("feature_request_email_recipient")
    recipients = [email.strip() for email in (recipient_config.value or "").split(",") if email.strip()]
    if not recipients:
      raise Exception("Feature request email recipient is not configured")
    html = EmailUtil.create_template(
      "feature_request_created.html",
      {
        "recipient_name": "CentCom Admin",
        "request_id": feature_request.get("request_id"),
        "request_title": feature_request.get("request_title"),
        "request_description": feature_request.get("request_description"),
        "request_business_impact": feature_request.get("request_business_impact"),
        "request_status": feature_request.get("request_status"),
        "request_priority": feature_request.get("request_priority"),
        "request_email": feature_request.get("request_email"),
        "request_date_submitted": feature_request.get("request_date_submitted"),
      },
    )
    EmailUtil.send(to=recipients, subject="New Customer Feature Request Submitted", html=html)
  except Exception as e:
    log_exception_with_traceback(e, context="Feature request notification email failed")


def create_feature_request(context, feature_request_data: dict) -> dict:
  session = context.session
  repository = FeatureRequestRepository(session)
  total_feature_requests_this_year = repository.get_total_feature_requests_this_year()
  feature_request_data["request_id"] = f"FR-{datetime.now().year}-{total_feature_requests_this_year + 1:04d}"

  feature_request = FeatureRequest(**feature_request_data)
  session.add(feature_request)
  session.flush()
  session.refresh(feature_request)
  result = {
    "id": feature_request.id,
    "request_id": feature_request.request_id,
    "request_title": feature_request.request_title,
    "request_description": feature_request.request_description,
    "request_status": feature_request.request_status.value,
    "request_priority": feature_request.request_priority.value,
    "request_email": feature_request.request_email,
    "request_business_impact": feature_request.request_business_impact,
    "request_attachments": feature_request.request_attachments,
    "request_date_submitted": feature_request.created_at.strftime("%B %d, %Y at %I:%M:%S %p SGT") if feature_request.created_at else "",
  }
  _send_feature_request_created_notification(session, result)
  return result


def update_feature_request(context, feature_request_id: int, feature_request_data: dict) -> dict:
  session = context.session
  repository = FeatureRequestRepository(session)
  feature_request = repository.get_by_id(feature_request_id)
  if not feature_request:
    raise Exception("Feature request not found")
  for field in (
    "request_title",
    "request_description",
    "request_business_impact",
    "request_attachments",
    "request_status",
    "request_priority",
    "request_email",
  ):
    if field in feature_request_data:
      setattr(feature_request, field, feature_request_data.get(field))
  session.flush()
  session.refresh(feature_request)
  return {
    "id": feature_request.id,
    "request_title": feature_request.request_title,
    "request_description": feature_request.request_description,
    "request_status": feature_request.request_status,
    "request_priority": feature_request.request_priority,
    "request_email": feature_request.request_email,
    "request_business_impact": feature_request.request_business_impact,
    "request_attachments": feature_request.request_attachments,
  }


def update_feature_request_status(
  context,
  feature_request_id: int,
  feature_request_status: FeatureRequestStatusEnum,
  feature_request_notes: str | None = None,
) -> dict:
  session = context.session
  repository = FeatureRequestRepository(session)
  feature_request = repository.get_by_id(feature_request_id)
  if not feature_request:
    raise Exception("Feature request not found")
  feature_request.request_status = feature_request_status
  feature_request.updated_at = datetime.now()
  if feature_request_notes:
    feature_request.request_notes = feature_request_notes
  session.flush()
  session.refresh(feature_request)
  return {
    "id": feature_request.id,
    "request_status": feature_request.request_status,
  }


def delete_feature_request(context, feature_request_id: int) -> None:
  session = context.session
  repository = FeatureRequestRepository(session)
  feature_request = repository.get_by_id(feature_request_id)
  if not feature_request:
    raise Exception("Feature request not found")
  session.delete(feature_request)
  session.flush()


def get_summary_data(context) -> dict:
  repository = FeatureRequestRepository(context.session)
  return {
    "total": repository.total_count(),
    "new": repository.get_feature_request_count(FeatureRequestStatusEnum.NEW),
    "under_review": repository.get_feature_request_count(FeatureRequestStatusEnum.UNDER_REVIEW),
    "added_to_roadmap": repository.get_feature_request_count(FeatureRequestStatusEnum.ADDED_TO_ROADMAP),
  }
