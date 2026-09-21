from database.entities.base import BaseModel

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.sql import func

from apps.app.utils.decorators.entity import Entity
from database.entities.base import Base

@Entity()
class UserPageAccessLog(Base):
	__tablename__ = "tblt_user_page_access_logs"

	id = sa.Column(sa.Integer,primary_key=True, autoincrement=True)
	user_session_id = sa.Column(
		UUID(as_uuid=True),
    sa.ForeignKey("tblt_user_sessions.id", ondelete="CASCADE"),
		nullable=False,
		index=True,
	)
	module_name = sa.Column(sa.String(100), nullable=False)
	page_name = sa.Column(sa.String(150), nullable=False)
	route_name = sa.Column(sa.String(150), nullable=False)
	url_path = sa.Column(sa.String(500), nullable=False)
	http_method = sa.Column(sa.String(10), nullable=True)
	access_datetime = sa.Column(sa.DateTime(timezone=True), nullable=False)
	created_at = sa.Column(sa.DateTime(timezone=True), nullable=False, server_default=func.now())
