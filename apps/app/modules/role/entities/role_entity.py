from database.entities.base import BaseModel

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.sql import func

from apps.app.utils.decorators.entity import Entity
from database.entities.base import Base
from sqlalchemy.orm import relationship

@Entity()
class Role(BaseModel):
	__tablename__ = "tblm_roles"

	id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
	name = sa.Column(sa.Text, nullable=False)
	description = sa.Column(sa.Text, nullable=True)
	enabled = sa.Column(sa.Boolean, nullable=False, default=True)
	is_default = sa.Column(sa.Boolean, nullable=False, default=False)
	created_by_user_id = sa.Column(sa.Integer, sa.ForeignKey("tblm_users.id"), nullable=False)
	created_by = relationship(
		"User",
		back_populates="created_roles",
		lazy="selectin",
		foreign_keys=[created_by_user_id],
	)
	updated_by_user_id = sa.Column(sa.Integer, sa.ForeignKey("tblm_users.id"), nullable=True)
	updated_by = relationship(
		"User",
		lazy="selectin",
		foreign_keys=[updated_by_user_id],
	)
