from database.entities.base import BaseModel

import sqlalchemy as sa
import enum

from apps.app.utils.decorators.entity import Entity


class RoleGroupPermissionEnum(str, enum.Enum):
	GET = "GET"
	POST = "POST"
	PUT = "PUT"
	PATCH = "PATCH"
	DELETE = "DELETE"


ROLE_GROUP_PERMISSION_ENUM = sa.Enum(
	RoleGroupPermissionEnum,
	name="role_group_permission",
	values_callable=lambda enum_cls: [member.value for member in enum_cls],
	create_type=True,
)

@Entity()
class RoleGroup(BaseModel):
	__tablename__ = "tblm_role_groups"

	id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
	role_id = sa.Column(sa.Integer, sa.ForeignKey("tblm_roles.id"), nullable=False)
	group_id = sa.Column(sa.Text, nullable=False)
	group_name = sa.Column(sa.Text, nullable=False)
	group_description = sa.Column(sa.Text, nullable=True)
	permission = sa.Column(ROLE_GROUP_PERMISSION_ENUM, nullable=False)
