from datetime import timedelta
from typing import Optional

from fastapi import HTTPException

from apps.app.core import services
from apps.app.utils import is_local
from apps.app.modules.role.service import role_service
from apps.app.modules.user.entities.user_entity import User
from apps.app.modules.user.repositories.users_repository import UsersRepository
from apps.app.modules.role.repositories.role_repository import RoleRepository
from apps.app.modules.role.repositories.role_group_repository import RoleGroupRepository
from apps.app.modules.user.service import user_role_service
from apps.app.utils.datetime import DateTime
from apps.app.utils.metrics import period_change
from database.session_factory import get_session


def _serialize_user_list_row(user) -> dict:
  return {
    "id": user.id,
    "name": user.name,
    "email": user.email,
    "last_name": user.last_name,
    "first_name": user.first_name,
    "is_active": user.is_active,
    "timezone": user.timezone if user.timezone else "",
    "role_id": user.role_id if user.role_id else None,
    "role": user.role.name if user.role else "",
    "title": user.title if user.title else "",
    "contact_number": user.contact_number if user.contact_number else "",
  }


def _summary_metric(total: int, current_period_count: int, previous_period_count: int) -> dict:
  return {"count": total, **period_change(current_period_count, previous_period_count)}


def _effective_role_name(context, user) -> str | None:
  if user.role:
    return user.role.name
  default_role = services.call(role_service.get_default_role)
  return default_role["name"] if default_role else None


def serialize_user(context, user) -> dict:
  return {
    "id": user.id,
    "name": user.name,
    "email": user.email,
    "first_name": user.first_name,
    "last_name": user.last_name,
    "title": user.title,
    "timezone": user.timezone,
    "okta_timezone": user.okta_timezone,
    "contact_number": user.contact_number,
    "is_active": user.is_active,
    "is_admin": user.is_admin,
    "admin_mode_enabled": user.effective_is_admin,
    "has_custom_permissions": user.custom_permissions is not None,
    "role_id": user.role_id,
    "role_name": _effective_role_name(context, user),
  }


def get_paginated_users(context, page: int = 1, page_size: int = 10, keyword: str = "", sort_field: str = "name", sort_direction: str = "asc", role_id: Optional[int] = None) -> dict:
  users, total = UsersRepository(context.session).get_users(page, page_size, keyword, sort_field, sort_direction, role_id)
  total_pages = total // page_size if total % page_size == 0 else total // page_size + 1
  return {
    "data": [_serialize_user_list_row(user) for user in users],
    "pagination": {
      "total": total,
      "page": page,
      "page_size": page_size,
      "total_pages": total_pages,
      "keyword": keyword,
      "sort_field": sort_field,
      "sort_direction": sort_direction,
    }
  }


def get_total_users() -> int:
  with get_session()() as session:
    return UsersRepository(session).total_count()


def get_user_by_id(context, user_id: str):
  return UsersRepository(context.session).get_by_id(user_id)


def get_user_summary_statistics(context, user: Optional[User] = None) -> dict:
  user_dt = DateTime(user)
  start_of_today = user_dt.now().replace(hour=0, minute=0, second=0, microsecond=0)
  start_of_this_month = start_of_today.replace(day=1)
  start_of_last_month = (start_of_this_month - timedelta(days=1)).replace(day=1)

  now_utc = user_dt.to_utc(user_dt.now())
  start_of_this_month_utc = user_dt.to_utc(start_of_this_month)
  start_of_last_month_utc = user_dt.to_utc(start_of_last_month)

  session = context.session
  users_repository = UsersRepository(session)
  role_repository = RoleRepository(session)

  users_this_month = users_repository.count_created_between(start_of_this_month_utc, now_utc)
  users_last_month = users_repository.count_created_between(start_of_last_month_utc, start_of_this_month_utc)

  roles_this_month = role_repository.count_created_between(start_of_this_month_utc, now_utc)
  roles_last_month = role_repository.count_created_between(start_of_last_month_utc, start_of_this_month_utc)

  return {
    "total_users": _summary_metric(users_repository.total_count(), users_this_month, users_last_month),
    "total_roles": _summary_metric(role_repository.total_count(), roles_this_month, roles_last_month),
  }


def update_user(context, user_id: int, user_data: dict) -> User:
  session = context.session
  repository = UsersRepository(session)
  user = repository.get_by_id(user_id)
  if not user:
    raise HTTPException(status_code=404, detail="User not found")

  if user_data.get("first_name") is not None:
    user.first_name = user_data.get("first_name")
  if user_data.get("last_name") is not None:
    user.last_name = user_data.get("last_name")
  if user_data.get("name") is not None:
    user.name = user_data.get("name")
  if user_data.get("email"):
    user.email = user_data.get("email")
  if user_data.get("is_active") is not None:
    user.is_active = bool(user_data.get("is_active"))
  if user_data.get("title") is not None:
    user.title = user_data.get("title")
  if user_data.get("contact_number") is not None:
    user.contact_number = user_data.get("contact_number")
  if user_data.get("timezone") is not None:
    user.timezone = user_data.get("timezone")

  session.flush()
  session.refresh(user)
  return user


def update_user_with_role(context, user_id: int, user_data: dict, role_id=None, has_role_update: bool = False, actor_user_id: Optional[int] = None) -> dict:
  if has_role_update:
    user_role_service.set_user_role(context, user_id, role_id, actor_user_id)
  updated_user = update_user(context, user_id, user_data)
  return serialize_user(context, updated_user)


def delete_user(context, user_id: int) -> None:
  deleted = UsersRepository(context.session).soft_delete_user(user_id)
  if not deleted:
    raise HTTPException(status_code=404, detail="User not found")


def get_current_user_permissions(context, user: User) -> dict:
  running_locally = is_local()

  if user.custom_permissions is not None:
    return {"is_admin": False, "is_local": running_locally, "permissions": user.custom_permissions}

  if user.effective_is_admin:
    return {"is_admin": True, "is_local": running_locally, "permissions": {}}

  session = context.session
  role_id = user.role_id
  if not role_id:
    default_role = RoleRepository(session).get_default_role()
    role_id = default_role.id if default_role else None

  if not role_id:
    return {"is_admin": False, "is_local": running_locally, "permissions": {}}

  role_groups = RoleGroupRepository(session).get_by_role_id(role_id)
  permissions: dict[str, list[str]] = {}
  for role_group in role_groups:
    value = role_group.permission.value if hasattr(role_group.permission, "value") else role_group.permission
    permissions.setdefault(role_group.group_id, []).append(value)
  return {"is_admin": False, "is_local": running_locally, "permissions": permissions}


def update_user_timezone(context, user_id: int, timezone: str) -> dict:
  updated_user = UsersRepository(context.session).update_timezone(user_id, timezone)
  return serialize_user(context, updated_user)
