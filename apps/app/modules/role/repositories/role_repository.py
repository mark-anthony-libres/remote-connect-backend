from sqlalchemy.orm import Session

from apps.app.modules.role.entities.role_entity import Role
from apps.app.utils.repositories.base_repository import BaseRepository
from apps.app.core.db import session_factory

class RoleRepository(BaseRepository[Role]):
  def __init__(self, db: Session | None = None):
    super().__init__(db or session_factory(), Role)


  def get_paginated_roles(
    self,
    page: int = 1,
    page_size: int = 10,
    keyword: str = "",
    sort_field: str = "name",
    sort_direction: str = "asc",
  ) -> list[Role]:
    query = self.db.query(Role)
    if keyword:
      query = query.filter(Role.name.ilike(f"%{keyword}%") | Role.description.ilike(f"%{keyword}%"))
    if sort_field and sort_direction:
      query = query.order_by(getattr(Role, sort_field).asc() if sort_direction == "asc" else getattr(Role, sort_field).desc())
    if page and page_size:
      query = query.offset((page - 1) * page_size).limit(page_size)
    roles = query.all()
    count = query.count()
    return roles, count

  def clear_default_flag(self) -> None:
    self.db.query(Role).filter(Role.is_default.is_(True)).update({"is_default": False})
    self.db.flush()

  def get_default_role(self) -> Role | None:
    return self.db.query(Role).filter(Role.is_default.is_(True)).first()

  def get_role_count(self, enabled: bool = True) -> int:
    query = self.db.query(Role)
    if enabled is not None:
      query = query.filter(Role.enabled == enabled)
    return query.count()
