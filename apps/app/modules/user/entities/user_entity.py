from database.entities.base import BaseModel

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.sql import func

from apps.app.utils.decorators.entity import Entity
from database.entities.base import Base
from sqlalchemy.orm import relationship
from apps.app.modules.role.entities.role_entity import Role
from apps.app.modules.miscellaneous.entities.feature_request_entity import FeatureRequest
from apps.app.modules.user.entities.user_role_entity import UserRole

@Entity()
class User(BaseModel):
	__tablename__ = "tblm_users"

	id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
	name = sa.Column(sa.Text, nullable=True)
	email = sa.Column(sa.Text, nullable=False, unique=True)
	first_name = sa.Column(sa.Text, nullable=True)
	last_name = sa.Column(sa.Text, nullable=True)

	is_active = sa.Column(sa.Boolean, nullable=False, server_default=sa.text("true"))

	title = sa.Column(sa.Text, nullable=True)
	timezone = sa.Column(sa.Text, nullable=True, server_default=sa.text(""))
	okta_timezone = sa.Column(sa.Text, nullable=True, server_default=sa.text("Asia/Singapore"))
	contact_number = sa.Column(sa.Text, nullable=True)
	deleted_at = sa.Column(sa.DateTime(timezone=True), nullable=True, default=None)
	is_admin = sa.Column(sa.Boolean, nullable=False, server_default=sa.text("false"))

	user_role = relationship(
		UserRole,
		uselist=False,
		lazy="selectin",
		foreign_keys=[UserRole.user_id],
		viewonly=True,
	)

	@property
	def role_id(self):
		return self.user_role.role_id if self.user_role else None

	@property
	def role(self):
		return self.user_role.role if self.user_role else None

	@property
	def effective_is_admin(self) -> bool:
		if not self.is_admin:
			return False
		from apps.app.core.auth.admin_override import is_admin_mode_suppressed

		return not is_admin_mode_suppressed(self.id)

	@property
	def custom_permissions(self) -> dict | None:
		if not self.is_admin:
			return None
		from apps.app.core.auth.admin_override import get_custom_permissions

		return get_custom_permissions(self.id)

	created_roles = relationship(
		Role,
		back_populates="created_by",
		foreign_keys=[Role.created_by_user_id],
		lazy="selectin",
	)


	created_feature_requests = relationship(
		FeatureRequest,
		back_populates="created_by",
		foreign_keys=[FeatureRequest.created_by_user_id],
		lazy="selectin",
	)

	reviewed_feature_requests = relationship(
		FeatureRequest,
		back_populates="reviewed_by",
		foreign_keys=[FeatureRequest.reviewed_by_user_id],
		lazy="selectin",
	)

	__table_args__ = (
	)
