from sqlalchemy.orm import Session

from apps.app.modules.role.entities.role_group_entity import RoleGroup
from apps.app.utils.repositories.base_repository import BaseRepository

class RoleGroupRepository(BaseRepository[RoleGroup]):
  def __init__(self, db: Session):
    super().__init__(db, RoleGroup)

  def get_by_role_id(self, role_id: int) -> list[RoleGroup]:
    return self.db.query(RoleGroup).filter(RoleGroup.role_id == role_id).all()

  def get_by_role_ids(self, role_ids: list[int]) -> list[RoleGroup]:
    if not role_ids:
      return []
    return self.db.query(RoleGroup).filter(RoleGroup.role_id.in_(role_ids)).all()

  def has_permission(self, role_id: int, group_id: str, permission: str) -> bool:
    return (
      self.db.query(RoleGroup.id)
      .filter(
        RoleGroup.role_id == role_id,
        RoleGroup.group_id == group_id,
        RoleGroup.permission == permission,
      )
      .first()
      is not None
    )

  def create_for_role(self, role_id: int, rows: list[dict]) -> None:
    for row in rows:
      self.db.add(RoleGroup(role_id=role_id, **row))
    self.db.flush()

  def delete_by_role_id(self, role_id: int) -> None:
    self.db.query(RoleGroup).filter(RoleGroup.role_id == role_id).delete()
    self.db.flush()
