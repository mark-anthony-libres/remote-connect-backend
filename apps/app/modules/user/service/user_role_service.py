from fastapi import HTTPException

from apps.app.modules.user.entities.user_role_entity import UserRole
from apps.app.modules.user.repositories.user_role_repository import UserRoleRepository


def _serialize_assignment(user_role: UserRole) -> dict:
  return {
    "id": user_role.id,
    "user_id": user_role.user_id,
    "user_email": user_role.assignee.email if user_role.assignee else None,
    "user_name": user_role.assignee.name if user_role.assignee else None,
    "role_id": user_role.role_id,
    "role_name": user_role.role.name if user_role.role else None,
    "role_description": user_role.role.description if user_role.role else None,
    "created_by_user_id": user_role.created_by_user_id,
    "created_by_user_name": user_role.created_by.name if user_role.created_by else None,
    "created_at": user_role.created_at.isoformat() if user_role.created_at else None,
  }


def is_role_already_assigned(session, user_id: int, role_id: int) -> bool:
  return UserRoleRepository(session).get_by_user_and_role(user_id, role_id) is not None


def get_paginated_assignments(
  context,
  page: int = 1,
  page_size: int = 10,
  keyword: str = "",
  sort_field: str = "created_at",
  sort_direction: str = "desc",
) -> dict:
  repository = UserRoleRepository(context.session)
  rows, total = repository.get_paginated(page=page, page_size=page_size, keyword=keyword, sort_field=sort_field, sort_direction=sort_direction)
  total_pages = total // page_size if total % page_size == 0 else total // page_size + 1
  return {
    "data": [_serialize_assignment(row) for row in rows],
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


def assign_role(context, user_id: int, role_id: int, actor_user_id: int) -> dict:
  session = context.session
  repository = UserRoleRepository(session)

  if is_role_already_assigned(session, user_id, role_id):
    raise HTTPException(status_code=400, detail="This role is already assigned to the selected user.")

  repository.delete_by_user_id(user_id)
  user_role = UserRole(user_id=user_id, role_id=role_id, created_by_user_id=actor_user_id)
  session.add(user_role)
  session.flush()
  session.refresh(user_role)
  return _serialize_assignment(user_role)


def remove_assignment(context, assignment_id: int) -> None:
  session = context.session
  repository = UserRoleRepository(session)
  user_role = repository.get_by_id(assignment_id)
  if not user_role:
    raise HTTPException(status_code=404, detail="Role assignment not found")
  session.delete(user_role)
  session.flush()


def set_user_role(context, user_id: int, role_id: int | None, actor_user_id: int) -> None:
  session = context.session
  repository = UserRoleRepository(session)
  current = repository.get_by_user_id(user_id)
  current_role_id = current.role_id if current else None

  if current_role_id == role_id:
    return

  repository.delete_by_user_id(user_id)
  if role_id:
    session.add(UserRole(user_id=user_id, role_id=role_id, created_by_user_id=actor_user_id))
    session.flush()
