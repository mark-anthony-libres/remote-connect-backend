from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from apps.app.core.db import session_factory
from apps.app.modules.user.entities.user_request_log_summary_entity import UserRequestLogSummary
from apps.app.utils.repositories.base_repository import BaseRepository


class UserRequestLogSummaryRepository(BaseRepository[UserRequestLogSummary]):
  def __init__(self, db: Optional[Session] = None):
    super().__init__(db or session_factory(), UserRequestLogSummary)

  def record_summary(
    self,
    user_id: int,
    session_id: Optional[UUID],
    endpoint: str,
    is_cached: bool,
    request_count: int,
    average_response_time: float,
  ) -> UserRequestLogSummary:
    return self.create(
      UserRequestLogSummary(
        user_id=user_id,
        session_id=session_id,
        endpoint=endpoint,
        is_cached=is_cached,
        request_count=request_count,
        average_response_time=average_response_time,
      )
    )

  def delete_older_than(self, retention_days: int) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    deleted_count = (
      self.db.query(UserRequestLogSummary)
      .filter(UserRequestLogSummary.created_at < cutoff)
      .delete(synchronize_session=False)
    )
    self.db.commit()
    return deleted_count
