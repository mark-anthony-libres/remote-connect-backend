from database.entities.base import BaseModel

import sqlalchemy as sa
from sqlalchemy.sql import func

from apps.app.utils.decorators.entity import Entity


@Entity()
class AppConfiguration(BaseModel):
	__tablename__ = "tblm_app_configurations"

	id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
	name = sa.Column(sa.Text, nullable=False)
	label = sa.Column(sa.Text, nullable=True)
	value = sa.Column(sa.Text, nullable=False)
	active = sa.Column(sa.Boolean, nullable=False, default=True)
	created_at = sa.Column(sa.DateTime(timezone=True), nullable=False, server_default=func.now())
	updated_at = sa.Column(sa.DateTime(timezone=True), nullable=False, server_default=func.now())
