from database.entities.base import BaseModel

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from apps.app.utils.decorators.entity import Entity


@Entity()
class UserRequestLogSummary(BaseModel):
	__tablename__ = "tblm_user_request_log_summaries"

	id = sa.Column(sa.Integer, primary_key=True, autoincrement=True)
	user_id = sa.Column(sa.Integer, sa.ForeignKey("tblm_users.id", ondelete="CASCADE"), nullable=False)
	session_id = sa.Column(UUID(as_uuid=True), sa.ForeignKey("tblt_user_sessions.id", ondelete="SET NULL"), nullable=True)
	endpoint = sa.Column(sa.String, nullable=False)
	average_response_time = sa.Column(sa.Float, nullable=False)
	request_count = sa.Column(sa.Integer, nullable=False)
	is_cached = sa.Column(sa.Boolean(), nullable=False)
