from fastapi import HTTPException

from apps.app.modules.role.repositories.role_repository import RoleRepository
from apps.app.modules.role.repositories.role_group_repository import RoleGroupRepository
from apps.app.modules.user.repositories.user_role_repository import UserRoleRepository
from apps.app.modules.role.entities.role_entity import Role
from apps.app.modules.role.entities.role_group_entity import RoleGroupPermissionEnum
from infra.groups import ALL_GROUPS
from apps.app.modules.role.service.group_hierarchy import get_ancestor_ids

_GROUPS_BY_ID = {group.id: group for group in ALL_GROUPS}
_VALID_PERMISSIONS = {member.value for member in RoleGroupPermissionEnum}
_ELEVATED_PERMISSIONS = {value for value in _VALID_PERMISSIONS if value != "GET"}

def _build_permissions_map(role_groups) -> dict:
  permissions: dict[str, list[str]] = {}
  for role_group in role_groups:
    value = role_group.permission.value if hasattr(role_group.permission, "value") else role_group.permission
    permissions.setdefault(role_group.group_id, []).append(value)
  return permissions

def _apply_permission_dependencies(permissions: dict) -> dict:
  result = {group_id: list(methods) for group_id, methods in (permissions or {}).items()}
  changed = True
  while changed:
    changed = False
    for group_id in list(result.keys()):
      methods = result[group_id]
      if "GET" not in methods and any(method in _ELEVATED_PERMISSIONS for method in methods):
        methods.append("GET")
        changed = True
    for group_id, methods in list(result.items()):
      for method in list(methods):
        for ancestor_id in get_ancestor_ids(group_id):
          ancestor_methods = result.setdefault(ancestor_id, [])
          if method not in ancestor_methods:
            ancestor_methods.append(method)
            changed = True
  return result

def _resolve_role_group_rows(permissions: dict) -> list[dict]:
  rows = []
  for group_id, methods in _apply_permission_dependencies(permissions).items():
    group = _GROUPS_BY_ID.get(group_id)
    if not group or not methods:
      continue
    for method in methods:
      if method not in _VALID_PERMISSIONS:
        continue
      rows.append({
        "group_id": group.id,
        "group_name": group.name,
        "group_description": group.description,
        "permission": method,
      })
  return rows

def _serialize_role(role, role_groups) -> dict:
  explicit_permissions = _build_permissions_map(role_groups)
  return {
    "id": role.id,
    "name": role.name,
    "description": role.description,
    "enabled": role.enabled,
    "is_default": role.is_default,
    "permissions": explicit_permissions,
    "created_by_user_id": role.created_by_user_id,
    "created_by_user_name": role.created_by.name,
    "updated_by_user_id": role.updated_by_user_id,
    "updated_by_user_name": role.updated_by.name if role.updated_by else None,
    "created_at": role.created_at.isoformat() if role.created_at else None,
    "updated_at": role.updated_at.isoformat() if role.updated_at else None,
  }

def _serialize_roles(session, roles) -> list[dict]:
  role_group_repository = RoleGroupRepository(session)
  role_groups_by_role_id: dict[int, list] = {}
  for role_group in role_group_repository.get_by_role_ids([role.id for role in roles]):
    role_groups_by_role_id.setdefault(role_group.role_id, []).append(role_group)
  return [_serialize_role(role, role_groups_by_role_id.get(role.id, [])) for role in roles]


def get_all_roles(context) -> list[dict]:
  session = context.session
  roles = RoleRepository(session).all()
  return _serialize_roles(session, roles)


def get_paginated_roles(
  context,
  page: int = 1,
  page_size: int = 10,
  keyword: str = "",
  sort_field: str = "name",
  sort_direction: str = "asc",
) -> dict:
  session = context.session
  roles, total = RoleRepository(session).get_paginated_roles(page=page, page_size=page_size, keyword=keyword, sort_field=sort_field, sort_direction=sort_direction)
  total_pages = total // page_size if total % page_size == 0 else total // page_size + 1
  return {
    "data": _serialize_roles(session, roles),
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


def get_default_role(context) -> dict | None:
  session = context.session
  role = RoleRepository(session).get_default_role()
  if not role:
    return None
  role_groups = RoleGroupRepository(session).get_by_role_id(role.id)
  return _serialize_role(role, role_groups)


def get_role_by_id(context, role_id: int) -> dict:
  session = context.session
  role = RoleRepository(session).get_by_id(role_id)
  if not role:
    raise HTTPException(status_code=404, detail="Role not found")
  role_groups = RoleGroupRepository(session).get_by_role_id(role.id)
  return _serialize_role(role, role_groups)


def create_role(context, role_data: dict) -> dict:
  session = context.session
  permissions = role_data.pop("permissions", None) or {}
  role_group_repository = RoleGroupRepository(session)

  role = Role(**role_data)
  session.add(role)
  session.flush()
  session.refresh(role)

  role_group_rows = _resolve_role_group_rows(permissions)
  role_group_repository.create_for_role(role.id, role_group_rows)
  role_groups = role_group_repository.get_by_role_id(role.id)
  return _serialize_role(role, role_groups)


def update_role(context, role_id: int, role_data: dict) -> dict:
  session = context.session
  repository = RoleRepository(session)
  role_group_repository = RoleGroupRepository(session)

  role = repository.get_by_id(role_id)
  if not role:
    raise HTTPException(status_code=404, detail="Role not found")

  if role_data.get("name") is not None:
    role.name = role_data.get("name")
  if role_data.get("description") is not None:
    role.description = role_data.get("description")
  if role_data.get("enabled") is not None:
    role.enabled = bool(role_data.get("enabled"))
  if role_data.get("updated_by_user_id") is not None:
    role.updated_by_user_id = role_data.get("updated_by_user_id")

  session.flush()
  session.refresh(role)

  if role_data.get("permissions") is not None:
    role_group_rows = _resolve_role_group_rows(role_data.get("permissions"))
    role_group_repository.delete_by_role_id(role.id)
    role_group_repository.create_for_role(role.id, role_group_rows)

  role_groups = role_group_repository.get_by_role_id(role.id)
  return _serialize_role(role, role_groups)


def set_default_role(context, role_id: int, is_default: bool) -> dict:
  session = context.session
  repository = RoleRepository(session)
  role = repository.get_by_id(role_id)
  if not role:
    raise HTTPException(status_code=404, detail="Role not found")

  if is_default:
    repository.clear_default_flag()
    role.is_default = True
    session.flush()
    session.refresh(role)
    UserRoleRepository(session).delete_by_role_id(role.id)
  else:
    role.is_default = False
    session.flush()
    session.refresh(role)

  role_groups = RoleGroupRepository(session).get_by_role_id(role.id)
  return _serialize_role(role, role_groups)


def delete_role(context, role_id: int) -> None:
  session = context.session
  repository = RoleRepository(session)
  role = repository.get_by_id(role_id)
  if not role:
    raise HTTPException(status_code=404, detail="Role not found")
  if role.is_default:
    raise HTTPException(status_code=400, detail="The default role cannot be deleted.")
  RoleGroupRepository(session).delete_by_role_id(role_id)
  UserRoleRepository(session).delete_by_role_id(role_id)

  session.delete(role)
  session.flush()


def get_summary_data(context) -> dict:
  repository = RoleRepository(context.session)
  return {
    "total_roles": repository.total_count(),
    "total_enabled_roles": repository.get_role_count(enabled=True),
    "total_disabled_roles": repository.get_role_count(enabled=False),
  }
