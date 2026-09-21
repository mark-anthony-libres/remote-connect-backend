import json
from typing import List, Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, UploadFile

from apps.app.core import services
from apps.app.core.auth.dependencies import get_current_user
from apps.app.core.errors import handle_route_errors
from apps.app.modules.miscellaneous.entities.feature_request_entity import (
  FeatureRequestPriorityEnum,
  FeatureRequestStatusEnum,
)
from apps.app.modules.miscellaneous.service import feature_request_service
from apps.app.modules.user.entities.user_entity import User
from apps.app.utils import log_exception_with_traceback
from apps.app.utils.s3 import S3Util
from infra.groups import g_feature_request

router = APIRouter(prefix=f"/{g_feature_request.id}")

VALID_ATTACHMENT_EXTENSIONS = (".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".jpg", ".jpeg", ".png", ".gif", ".zip")
MAX_ATTACHMENT_SIZE_BYTES = 10 * 1024 * 1024


@router.get("")
@handle_route_errors(context="Feature requests retrieval failed")
def all(
  page: Optional[int] = Query(default=1),
  page_size: Optional[int] = Query(default=15),
  keyword: Optional[str] = Query(default=""),
  sort_field: Optional[str] = Query(default="created_at"),
  sort_direction: Optional[str] = Query(default="desc"),
  request_status: Optional[str] = Query(default=None),
  request_priority: Optional[str] = Query(default=None),
):
  return services.call(
    feature_request_service.get_paginated_feature_requests,
    page=page, page_size=page_size, keyword=keyword, sort_field=sort_field, sort_direction=sort_direction, request_status=request_status, request_priority=request_priority,
  )


@router.get("/my-requests")
@handle_route_errors(context="My feature requests retrieval failed")
def my_requests(
  page: Optional[int] = Query(default=1),
  page_size: Optional[int] = Query(default=15),
  keyword: Optional[str] = Query(default=""),
  sort_field: Optional[str] = Query(default="created_at"),
  sort_direction: Optional[str] = Query(default="desc"),
  request_status: Optional[str] = Query(default=None),
  current_user: User = Depends(get_current_user),
):
  return services.call(
    feature_request_service.get_paginated_feature_requests,
    page=page, page_size=page_size, keyword=keyword, sort_field=sort_field, sort_direction=sort_direction, request_status=request_status, user_id=current_user.id,
  )


@router.get("/summary")
@handle_route_errors(context="Feature request summary retrieval failed")
def get_summary():
  return {"data": services.call(feature_request_service.get_summary_data)}


@router.get("/{feature_request_id}")
@handle_route_errors(context="Feature request retrieval failed")
def get_by_id(feature_request_id: int):
  return {"data": services.call(feature_request_service.get_feature_request_by_id, feature_request_id=feature_request_id)}


@router.post("")
@handle_route_errors(context="Feature request creation failed")
async def create(
  request_email: str = Form(...),
  request_title: str = Form(...),
  request_description: str = Form(...),
  request_business_impact: Optional[str] = Form(default=None),
  request_priority: str = Form(...),
  request_file: Optional[List[UploadFile]] = File(default=None),
  current_user: User = Depends(get_current_user),
):
  if request_priority not in [
    FeatureRequestPriorityEnum.LOW.value,
    FeatureRequestPriorityEnum.MEDIUM.value,
    FeatureRequestPriorityEnum.HIGH.value,
  ]:
    raise HTTPException(status_code=400, detail="Invalid request priority")
  if not request_email:
    raise HTTPException(status_code=400, detail="Request email is required")
  if not request_title:
    raise HTTPException(status_code=400, detail="Request title is required")
  if not request_description:
    raise HTTPException(status_code=400, detail="Request description is required")

  uploaded_files = [file for file in (request_file or []) if file and file.filename]
  for file in uploaded_files:
    if f".{file.filename.split('.')[-1]}" not in VALID_ATTACHMENT_EXTENSIONS:
      raise HTTPException(status_code=400, detail="Invalid file extension")
    if file.size > MAX_ATTACHMENT_SIZE_BYTES:
      raise HTTPException(status_code=400, detail="File size is too large")

  request_attachments: list[str] = []
  try:
    for file in uploaded_files:
      file_details = await S3Util.upload_feature_request_file(file)
      request_attachments.append(json.dumps(file_details))
  except Exception as e:
    log_exception_with_traceback(e, context="Feature request attachment upload failed")
    raise HTTPException(status_code=500, detail="Failed to upload attachment") from e

  feature_request_data = {
    "created_by_user_id": current_user.id,
    "request_email": request_email,
    "request_title": request_title,
    "request_description": request_description,
    "request_business_impact": request_business_impact,
    "request_status": FeatureRequestStatusEnum.NEW.value,
    "request_priority": request_priority,
    "request_attachments": request_attachments or None,
  }
  return {"data": services.call(feature_request_service.create_feature_request, feature_request_data=feature_request_data)}


@router.patch("/{feature_request_id}/status")
@handle_route_errors(context="Feature request status update failed")
def update_status(feature_request_id: int, body: dict = Body(default={})):
  request_status = body.get("request_status")
  request_notes: Optional[str] = body.get("request_notes")
  try:
    status_enum = FeatureRequestStatusEnum(request_status)
  except ValueError:
    raise HTTPException(status_code=400, detail="Invalid request status")
  return {
    "data": services.call(
      feature_request_service.update_feature_request_status,
      feature_request_id=feature_request_id, feature_request_status=status_enum, feature_request_notes=request_notes,
    )
  }


@router.put("/{feature_request_id}")
@handle_route_errors(context="Feature request update failed")
def update(feature_request_id: int, body: dict = Body(default={})):
  feature_request_data = {
    "request_email": body.get("request_email"),
    "request_title": body.get("request_title"),
    "request_description": body.get("request_description"),
    "request_business_impact": body.get("request_business_impact"),
    "request_status": body.get("request_status"),
    "request_priority": body.get("request_priority"),
    "request_attachments": body.get("request_attachments"),
  }
  return {
    "data": services.call(
      feature_request_service.update_feature_request,
      feature_request_id=feature_request_id, feature_request_data=feature_request_data,
    )
  }


@router.delete("/{feature_request_id}")
@handle_route_errors(context="Feature request deletion failed")
def delete(feature_request_id: int):
  services.call(feature_request_service.delete_feature_request, feature_request_id=feature_request_id)
  return {"message": "Feature request deleted successfully"}
