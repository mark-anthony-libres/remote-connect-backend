from sqlalchemy.orm import Session, aliased

from apps.app.modules.user.entities.user_role_entity import UserRole
from apps.app.modules.user.entities.user_entity import User
from apps.app.modules.role.entities.role_entity import Role
from apps.app.utils.repositories.base_repository import BaseRepository


class UserRoleRepository(BaseRepository[UserRole]):
  def __init__(self, db: Session):
    super().__init__(db, UserRole)

  def get_by_user_id(self, user_id: int) -> UserRole | None:
    return self.db.query(UserRole).filter(UserRole.user_id == user_id).first()

  def get_by_user_and_role(self, user_id: int, role_id: int) -> UserRole | None:
    return self.db.query(UserRole).filter(UserRole.user_id == user_id, UserRole.role_id == role_id).first()

  def delete_by_user_id(self, user_id: int) -> None:
    self.db.query(UserRole).filter(UserRole.user_id == user_id).delete()
    self.db.flush()

  def delete_by_role_id(self, role_id: int) -> None:
    self.db.query(UserRole).filter(UserRole.role_id == role_id).delete()
    self.db.flush()

  def get_paginated(
    self,
    page: int = 1,
    page_size: int = 10,
    keyword: str = "",
    sort_field: str = "created_at",
    sort_direction: str = "desc",
  ):
    Assignee = aliased(User)
    CreatedBy = aliased(User)
    query = (
      self.db.query(UserRole)
      .join(Assignee, UserRole.user_id == Assignee.id)
      .join(Role, UserRole.role_id == Role.id)
      .join(CreatedBy, UserRole.created_by_user_id == CreatedBy.id)
    )
    if keyword:
      query = query.filter(
        Assignee.email.ilike(f"%{keyword}%") |
        Assignee.name.ilike(f"%{keyword}%") |
        Role.name.ilike(f"%{keyword}%")
      )
    if sort_field == "user_email":
      query = query.order_by(Assignee.email.asc() if sort_direction == "asc" else Assignee.email.desc())
    elif sort_field == "user_name":
      query = query.order_by(Assignee.name.asc() if sort_direction == "asc" else Assignee.name.desc())
    elif sort_field == "role":
      query = query.order_by(Role.name.asc() if sort_direction == "asc" else Role.name.desc())
    else:
      query = query.order_by(UserRole.created_at.asc() if sort_direction == "asc" else UserRole.created_at.desc())

    total = query.count()
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return rows, total
