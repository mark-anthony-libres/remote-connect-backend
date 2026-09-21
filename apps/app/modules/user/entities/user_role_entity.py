from database.entities.base import BaseModel

import sqlalchemy as sa
from sqlalchemy.orm import relationship

from apps.app.utils.decorators.entity import Entity

@Entity()
class UserRole(BaseModel):
	__tablename__ = "tblm_user_role"

	id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
	user_id = sa.Column(sa.Integer, sa.ForeignKey("tblm_users.id"), nullable=False, unique=True)
	role_id = sa.Column(sa.Integer, sa.ForeignKey("tblm_roles.id"), nullable=False)
	created_by_user_id = sa.Column(sa.Integer, sa.ForeignKey("tblm_users.id"), nullable=False)

	role = relationship(
		"Role",
		lazy="selectin",
		foreign_keys=[role_id],
	)
	assignee = relationship(
		"User",
		lazy="selectin",
		foreign_keys=[user_id],
	)
	created_by = relationship(
		"User",
		lazy="selectin",
		foreign_keys=[created_by_user_id],
	)
