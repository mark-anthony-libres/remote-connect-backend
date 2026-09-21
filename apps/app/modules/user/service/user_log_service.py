from apps.app.modules.user.repositories.user_sessions_resposity import UserSessionsRepository
from apps.app.modules.user.repositories.users_repository import UsersRepository
from apps.app.modules.user.repositories.users_repository import UsersTimePeriodEnum
from apps.app.modules.user.repositories.user_page_access_log_repository import UserPageAccessLogRepository
from apps.app.modules.user.entities.user_entity import User
from apps.app.utils.datetime import DateTime
from apps.app.utils.metrics import period_change
from typing import Optional
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

def get_performance_indicators(context, user: Optional[User] = None) -> dict:
  user_dt = DateTime(user)
  start_of_today = user_dt.now().replace(hour=0, minute=0, second=0, microsecond=0)
  start_of_this_month = start_of_today.replace(day=1)
  start_of_last_month = (start_of_this_month - timedelta(days=1)).replace(day=1)

  now_utc = user_dt.to_utc(user_dt.now())
  start_of_this_month_utc = user_dt.to_utc(start_of_this_month)
  start_of_last_month_utc = user_dt.to_utc(start_of_last_month)

  session = context.session
  users_repository = UsersRepository(session)
  user_sessions_repository = UserSessionsRepository(session)

  total_users = users_repository.total_count()
  registered_users_last_month = users_repository.count_created_between(start_of_last_month_utc, start_of_this_month_utc)
  registered_users_this_month = users_repository.count_created_between(start_of_this_month_utc, now_utc)
  registered_users_change = period_change(registered_users_this_month, registered_users_last_month)

  total_login_count = user_sessions_repository.get_total_sessions()
  total_login_count_last_month = user_sessions_repository.count_sessions_between(start_of_last_month_utc, start_of_this_month_utc)
  total_login_count_this_month = user_sessions_repository.count_sessions_between(start_of_this_month_utc, now_utc)
  total_login_count_change = period_change(total_login_count_this_month, total_login_count_last_month)

  users_as_of_start_of_this_month = users_repository.count_created_before(start_of_this_month_utc)
  average_login_this_month = total_login_count_this_month / total_users if total_users > 0 else 0
  average_login_last_month = total_login_count_last_month / users_as_of_start_of_this_month if users_as_of_start_of_this_month > 0 else 0
  average_login_change = period_change(average_login_this_month, average_login_last_month)

  return {
    "total_users": {
      "count": total_users,
      **registered_users_change,
    },
    "active_users_today": users_repository.get_active_users(time_period=UsersTimePeriodEnum.TODAY, user_dt=user_dt),
    "active_users_this_week": users_repository.get_active_users(time_period=UsersTimePeriodEnum.WEEK, user_dt=user_dt),
    "active_users_this_month": users_repository.get_active_users(time_period=UsersTimePeriodEnum.MONTH, user_dt=user_dt),
    "total_login_count": {
      "count": total_login_count,
      **total_login_count_change,
    },
    "average_login_per_user": {
      "count": users_repository.get_average_login_per_user(),
      **average_login_change,
    },
  }

def get_top_active_users(context) -> list[dict]:
  users_repository = UsersRepository(context.session)
  return users_repository.get_top_active_users(days=30)

def get_daily_login_trends(context, from_date: Optional[datetime] = None, to_date: Optional[datetime] = None, user_id: Optional[str] = None) -> list[dict]:
  session = context.session
  time_zone = "UTC"
  if user_id:
    user = UsersRepository(session).get_by_id(user_id)
    if user and user.timezone:
      time_zone = user.timezone

  tz = ZoneInfo(time_zone) if time_zone else timezone.utc
  now_local = datetime.now(tz).replace(tzinfo=None)
  if (not from_date or not to_date) or (from_date == to_date):
    from_date = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    to_date = now_local.replace(hour=23, minute=59, second=59, microsecond=999999)
    by_date = False
  else:
    by_date = True
    to_date = to_date.replace(hour=23, minute=59, second=59, microsecond=999999)

  user_sessions_repository = UserSessionsRepository(session)
  return user_sessions_repository.get_login_trends(from_date=from_date, to_date=to_date, by_date=by_date, time_zone=time_zone)

def get_recent_login_history(
  context,
  keyword: Optional[str] = None,
  from_date: Optional[datetime] = None,
  to_date: Optional[datetime] = None,
  user: Optional[User] = None,
  page: int = 1,
  page_size: int = 10,
) -> dict:
  user_dt = DateTime(user)
  if to_date:
    to_date = to_date.replace(hour=23, minute=59, second=59, microsecond=999999)
  from_utc = user_dt.to_utc(from_date) if from_date else None
  to_utc = user_dt.to_utc(to_date) if to_date else None
  user_sessions_repository = UserSessionsRepository(context.session)
  rows, total = user_sessions_repository.get_recent_login_history(
    keyword=keyword, from_date=from_utc, to_date=to_utc, page=page, page_size=page_size
  )
  for row in rows:
    login_dt = user_dt.from_utc(row["login_datetime"])
    logout_dt = user_dt.from_utc(row["logout_datetime"])
    row["login_datetime"] = login_dt.isoformat() if login_dt else None
    row["logout_datetime"] = logout_dt.isoformat() if logout_dt else None
  total_pages = total // page_size if total % page_size == 0 else total // page_size + 1
  return {
    "data": rows,
    "pagination": {
      "total": total,
      "page": page,
      "page_size": page_size,
      "total_pages": total_pages,
    },
  }

def get_most_visited_pages(context) -> list[dict]:
  user_page_access_log_repository = UserPageAccessLogRepository(context.session)
  return user_page_access_log_repository.get_most_visited_pages(limit=10)

def get_sessions_by_role(context) -> list[dict]:
  user_sessions_repository = UserSessionsRepository(context.session)
  return user_sessions_repository.get_sessions_by_role()


def get_current_user_page_access_logs(context, user_id) -> Optional[list]:
  session = context.session
  user_session = UserSessionsRepository(session).get_active_session(user_id)
  if not user_session:
    return None
  return UserPageAccessLogRepository(session).get_all_by_session_id(session_id=int(user_session.id))


def resolve_active_session_id(context, user_id) -> Optional[int]:
  user_session = UserSessionsRepository(context.session).get_active_session(user_id)
  return user_session.id if user_session else None


def record_user_page_access_log(context, user_page_access_log_data: dict) -> None:
  UserPageAccessLogRepository(context.session).create(user_page_access_log_data)
