from sqlalchemy import func
from sqlalchemy.orm import Session

from apps.app.modules.user.entities.user_page_access_log_entity import UserPageAccessLog
from apps.app.utils.repositories.base_repository import BaseRepository

class UserPageAccessLogRepository(BaseRepository[UserPageAccessLog]):
  def __init__(self, db: Session):
    super().__init__(db, UserPageAccessLog)

  def create(self, user_page_access_log_data: dict):
    user_page_access_log = UserPageAccessLog(**user_page_access_log_data)
    self.db.add(user_page_access_log)
    self.db.flush()
    self.db.refresh(user_page_access_log)
    return user_page_access_log

  def get_all_by_session_id(self, session_id: int):
    user_page_access_logs = (self.db.query(UserPageAccessLog).filter(UserPageAccessLog.user_session_id == session_id).all())
    return user_page_access_logs

  def get_most_visited_pages(self, limit: int = 10):
    most_visited_pages = (self.db.query(UserPageAccessLog.page_name, func.count(UserPageAccessLog.id).label('count'))
      .where(UserPageAccessLog.page_name != 'Login')
      .where(UserPageAccessLog.page_name != 'Logout')
      .group_by(UserPageAccessLog.page_name)
      .order_by(func.count(UserPageAccessLog.page_name).desc(), UserPageAccessLog.page_name.asc())
      .limit(limit)
      .all()
    )
    return [
      {
        "page_name": row.page_name,
        "count": row.count
      } for row in most_visited_pages
    ]
