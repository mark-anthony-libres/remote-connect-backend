from fastapi import APIRouter, Body, status, Depends, HTTPException, Request
from apps.app.utils import log_exception_with_traceback
from apps.app.core import services
from apps.app.core.errors import handle_route_errors
from apps.app.core.auth.dependencies import get_current_user
from apps.app.core.auth.decorators import SkipGroupPermission
from apps.app.core.settings import settings
from apps.app.utils.datetime import AVAILABLE_TIMEZONES
from apps.app.modules.user.entities.user_entity import User
from apps.app.core.cache_builder import remove_user_cache_sync
from apps.app.modules.user.service import user_service
from apps.app.modules.user.service import user_role_service
from apps.app.modules.role.service import role_service
from apps.app.core.auth import admin_override
from fastapi import Query
from typing import Optional
from infra.groups import g_user, ALL_GROUPS
from apps.app.core.auth.route_binding import collect_group_permissions

router = APIRouter(prefix=f"/{g_user.id}")
_GROUP_IDS = {group.id for group in ALL_GROUPS}

@router.get("")
@handle_route_errors(context="Users retrieval failed")
def list_users(
  page: Optional[int] = Query(default=1),
  page_size: Optional[int] = Query(default=15),
  keyword: Optional[str] = Query(default=""),
  sort_field: Optional[str] = Query(default="name"),
  sort_direction: Optional[str] = Query(default="asc"),
  role_id: Optional[int] = Query(default=None),
  user: User = Depends(get_current_user),
):
  return services.call(user_service.get_paginated_users, page=page, page_size=page_size, keyword=keyword, sort_field=sort_field, sort_direction=sort_direction, role_id=role_id)


@router.get("/timezones")
@SkipGroupPermission()
def get_timezones():
  return {"data": AVAILABLE_TIMEZONES}


@router.get("/me")
@SkipGroupPermission()
def get_me(user: User = Depends(get_current_user)):
  return {"data": services.call(user_service.serialize_user, user)}


@router.get("/me/permissions")
@SkipGroupPermission()
@handle_route_errors(context="User permissions retrieval failed")
def get_my_permissions(user: User = Depends(get_current_user)):
  permissions = services.call(user_service.get_current_user_permissions, user)
  return {"data": permissions}


@router.post("/me/admin-mode")
@SkipGroupPermission()
@handle_route_errors(context="Admin mode toggle failed")
def set_admin_mode(body: dict = Body(default={}), user: User = Depends(get_current_user)):
  if not user.is_admin:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges are required.")

  if bool(body.get("enabled")):
    admin_override.restore_admin_mode(user.id)
  else:
    if admin_override.get_custom_permissions(user.id) is not None:
      raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Restore standard permissions before disabling admin mode.")
    admin_override.suppress_admin_mode(user.id)

  remove_user_cache_sync(user.id)
  return {"data": services.call(user_service.serialize_user, user)}


@router.get("/me/role")
@SkipGroupPermission()
@handle_route_errors(context="Current role retrieval failed")
def get_my_role(user: User = Depends(get_current_user)):
  if user.role_id:
    return {"data": services.call(role_service.get_role_by_id, user.role_id)}
  return {"data": services.call(role_service.get_default_role)}


@router.get("/me/custom-permissions")
@SkipGroupPermission()
@handle_route_errors(context="Custom permissions retrieval failed")
def get_my_custom_permissions(user: User = Depends(get_current_user)):
  return {"data": user.custom_permissions}


@router.put("/me/custom-permissions")
@SkipGroupPermission()
@handle_route_errors(context="Custom permissions update failed")
def set_my_custom_permissions(request: Request, body: dict = Body(default={}), user: User = Depends(get_current_user)):
  if not user.is_admin:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges are required.")

  permissions = body.get("permissions")
  if not isinstance(permissions, dict) or not permissions:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="permissions is required")

  catalog = collect_group_permissions(request.app.routes, settings.api_prefix or "")
  for group_id, methods in permissions.items():
    if group_id not in _GROUP_IDS:
      raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown group: {group_id}")
    if not isinstance(methods, list) or not set(methods).issubset(catalog.get(group_id, set())):
      raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid permissions for group: {group_id}")

  admin_override.set_custom_permissions(user.id, permissions)
  remove_user_cache_sync(user.id)
  return {"data": services.call(user_service.serialize_user, user)}


@router.delete("/me/custom-permissions")
@SkipGroupPermission()
@handle_route_errors(context="Custom permissions removal failed")
def clear_my_custom_permissions(user: User = Depends(get_current_user)):
  if not user.is_admin:
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges are required.")
  admin_override.clear_custom_permissions(user.id)
  remove_user_cache_sync(user.id)
  return {"data": services.call(user_service.serialize_user, user)}


@router.patch("/me/timezone")
@SkipGroupPermission()
@handle_route_errors(context="Failed to update user timezone")
def update_my_timezone(body: dict = Body(default={}), user: User = Depends(get_current_user)):
  timezone = body.get("timezone")
  if not timezone:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="timezone is required")
  if timezone not in AVAILABLE_TIMEZONES:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid timezone")

  result = services.call(user_service.update_user_timezone, user.id, timezone)

  try:
    remove_user_cache_sync(user.id)
  except Exception as e:
    log_exception_with_traceback(e, context="Failed to clear user cache after timezone update")

  return {"data": result}


@router.get("/summary-statistics")
@handle_route_errors(context="User summary statistics retrieval failed")
def get_summary_statistics(user: User = Depends(get_current_user)):
  summary_statistics = services.call(user_service.get_user_summary_statistics, user=user)
  return {"data": summary_statistics}


@router.put("/{user_id}")
@handle_route_errors(context="User update failed")
def update_user(user_id: int, body: dict = Body(default={}), user: User = Depends(get_current_user)):
  user_data = {
    "first_name": body.get("first_name"),
    "last_name": body.get("last_name"),
    "name": body.get("name"),
    "email": body.get("email"),
    "title": body.get("title"),
    "contact_number": body.get("contact_number"),
    "timezone": body.get("timezone"),
    "is_active": body.get("is_active"),
  }

  result = services.call(
    user_service.update_user_with_role,
    user_id,
    user_data,
    role_id=body.get("role_id"),
    has_role_update="role_id" in body,
    actor_user_id=user.id,
  )
  return {"data": result}


@router.get("/role-assignments")
@handle_route_errors(context="Role assignments retrieval failed")
def list_role_assignments(
  page: Optional[int] = Query(default=1),
  page_size: Optional[int] = Query(default=15),
  keyword: Optional[str] = Query(default=""),
  sort_field: Optional[str] = Query(default="created_at"),
  sort_direction: Optional[str] = Query(default="desc"),
  user: User = Depends(get_current_user),
):
  return services.call(user_role_service.get_paginated_assignments, page=page, page_size=page_size, keyword=keyword, sort_field=sort_field, sort_direction=sort_direction)


@router.post("/role-assignments")
@handle_route_errors(context="Role assignment failed")
def create_role_assignment(body: dict = Body(default={}), user: User = Depends(get_current_user)):
  target_user_id = body.get("user_id")
  role_id = body.get("role_id")
  if not target_user_id:
    raise HTTPException(status_code=400, detail="user_id is required")
  if not role_id:
    raise HTTPException(status_code=400, detail="role_id is required")
  assignment = services.call(user_role_service.assign_role, target_user_id, role_id, user.id)
  return {"data": assignment}


@router.delete("/role-assignments/{assignment_id}")
@handle_route_errors(context="Role assignment removal failed")
def delete_role_assignment(assignment_id: int):
  services.call(user_role_service.remove_assignment, assignment_id)
  return {"message": "Role assignment removed successfully"}


@router.delete("/{user_id}")
@handle_route_errors(context="User deletion failed")
def delete_user(user_id: int, user: User = Depends(get_current_user)):
  services.call(user_service.delete_user, user_id)
  return {"message": "User deleted successfully"}
