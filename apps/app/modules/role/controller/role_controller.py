from fastapi import APIRouter, HTTPException, Body, Depends, Request
from apps.app.core import services
from apps.app.core.errors import handle_route_errors
from apps.app.core.auth.decorators import AdminOnlyAccess, SkipGroupPermission
from apps.app.modules.role.service import role_service
from apps.app.modules.user.entities.user_entity import User
from apps.app.core.auth.dependencies import get_current_user
from infra.groups import g_role

router = APIRouter(prefix=f"/{g_role.id}")

@router.get("")
@SkipGroupPermission()
@handle_route_errors(context="Roles retrieval failed")
def all(
  page: int = 1,
  page_size: int = 10,
  keyword: str = "",
  sort_field: str = "name",
  sort_direction: str = "asc",
  paginate: bool = False,
):
  if paginate:
    return services.call(role_service.get_paginated_roles, page, page_size, keyword, sort_field, sort_direction)
  return services.call(role_service.get_all_roles)

@router.post("")
@handle_route_errors(context="Role creation failed")
def create(body: dict = Body(default={}), current_user: User = Depends(get_current_user)):
  name = body.get("name")
  if not name:
    raise HTTPException(status_code=400, detail="Name is required")

  role_data = {
    "created_by_user_id": current_user.id,
    "updated_by_user_id": current_user.id,
    "name": name,
    "description": body.get("description"),
    "permissions": body.get("permissions") or {},
  }
  role = services.call(role_service.create_role, role_data)
  return {"data": role}


@router.put("/{role_id}")
@handle_route_errors(context="Role update failed")
def update(role_id: int, body: dict = Body(default={}), current_user: User = Depends(get_current_user)):
  role_data = {
    "name": body.get("name"),
    "description": body.get("description"),
    "enabled": body.get("enabled"),
    "permissions": body.get("permissions"),
    "updated_by_user_id": current_user.id,
  }
  role = services.call(role_service.update_role, role_id, role_data)
  return {"data": role}

@router.patch("/{role_id}/default")
@AdminOnlyAccess()
@handle_route_errors(context="Default role update failed")
async def set_default(role_id: int, request: Request, body: dict = Body(default={})):
  is_default = bool(body.get("is_default"))
  role = services.call(role_service.set_default_role, role_id, is_default)
  return {"data": role}


@router.delete("/{role_id}")
@handle_route_errors(context="Role deletion failed")
def delete(role_id: int):
  services.call(role_service.delete_role, role_id)
  return {"message": "Role deleted successfully"}

@router.get("/summary")
@handle_route_errors(context="Summary data retrieval failed")
def summary():
  summary_data = services.call(role_service.get_summary_data)
  return {"data": summary_data}

@router.get("/default")
@SkipGroupPermission()
@handle_route_errors(context="Default role retrieval failed")
def get_default():
  role = services.call(role_service.get_default_role)
  return {"data": role}
