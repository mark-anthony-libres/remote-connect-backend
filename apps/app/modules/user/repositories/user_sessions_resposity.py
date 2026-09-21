from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import re
from sqlalchemy import and_, func, or_
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from apps.app.modules.user.entities.user_session_entity import (
  LoginSourceEnum,
  SessionStatusEnum,
  UserSession,
)
from apps.app.modules.user.entities.user_entity import User
from apps.app.modules.user.entities.user_role_entity import UserRole
from apps.app.modules.role.entities.role_entity import Role
from apps.app.utils.repositories.base_repository import BaseRepository

_SEC_CH_UA_BRANDS = [
  "Microsoft Edge",
  "Google Chrome",
  "Opera",
  "Brave",
]

_USER_AGENT_BROWSER_PATTERNS = [
  ("Microsoft Edge", re.compile(r"Edg(?:e|A|iOS)?/([\d.]+)", re.I)),
  ("Opera", re.compile(r"OPR/([\d.]+)", re.I)),
  ("Brave", re.compile(r"Brave/([\d.]+)", re.I)),
  ("Mozilla Firefox", re.compile(r"Firefox/([\d.]+)", re.I)),
  ("Google Chrome", re.compile(r"Chrome/([\d.]+)", re.I)),
  ("Safari", re.compile(r"Version/([\d.]+).*Safari", re.I)),
]

class UserSessionsRepository(BaseRepository[UserSession]):
  def __init__(self, db: Session):
    super().__init__(db, UserSession)

  def get_total_sessions(self) -> int:
    return self.db.query(UserSession).count()

  def count_sessions_between(self, start: datetime, end: datetime) -> int:
    return self.db.query(UserSession).filter(UserSession.login_datetime >= start, UserSession.login_datetime < end).count()

  def get_login_trends(self, from_date: datetime, to_date: datetime, by_date: bool = True, time_zone: Optional[str] = None) -> list[dict]:
    tz_name = time_zone or "UTC"
    tz = ZoneInfo(tz_name)

    from_utc = _to_utc(from_date, tz)
    to_utc = _to_utc(to_date, tz)

    local_login_dt = func.timezone(tz_name, UserSession.login_datetime)

    if by_date:
      login_date_expr = func.date(local_login_dt)
      results = (
        self.db.query(
          login_date_expr.label("login_date"),
          func.count(UserSession.id).label("login_count"),
        )
        .filter(UserSession.login_datetime >= from_utc, UserSession.login_datetime <= to_utc)
        .group_by(login_date_expr)
        .order_by(login_date_expr.desc())
        .all()
      )
      return [
        {
          "label": _format_date_label(row.login_date),
          "count": row.login_count,
        }
        for row in results
      ]
    else:
      hour_expr = func.extract("hour", local_login_dt)
      results = (
        self.db.query(
          hour_expr.label("login_hour"),
          func.count(UserSession.id).label("login_count"),
        )
        .filter(UserSession.login_datetime >= from_utc, UserSession.login_datetime <= to_utc)
        .group_by(hour_expr)
        .all()
      )
      counts_by_hour = {int(row.login_hour): row.login_count for row in results}
      max_hour = datetime.now(tz).hour + 1
      return [
        {
          "label": _format_hour_label(hour),
          "count": counts_by_hour.get(hour, 0),
        }
        for hour in range(max_hour)
      ]

  def get_recent_login_history(
    self,
    keyword: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    page: int = 1,
    page_size: int = 10,
  ) -> Tuple[list[dict], int]:
    query = (
      self.db.query(
        UserSession.login_datetime,
        UserSession.logout_datetime,
        UserSession.session_duration_seconds,
        UserSession.ip_address,
        UserSession.browser,
        UserSession.browser_version,
        UserSession.operating_system,
        UserSession.device_type,
        User.name,
        User.email,
        User.title,
        User.id,
        Role.name.label("role_name"),
      )
      .join(User, User.id == UserSession.user_id)
      .outerjoin(UserRole, UserRole.user_id == User.id)
      .outerjoin(Role, Role.id == UserRole.role_id)
    )
    if keyword:
      query = query.filter(User.name.ilike(f"%{keyword}%"))
    if from_date:
      query = query.filter(UserSession.login_datetime >= from_date)
    if to_date:
      query = query.filter(UserSession.login_datetime <= to_date)

    total = query.count()
    results = (
      query.order_by(UserSession.login_datetime.desc())
      .offset((page - 1) * page_size)
      .limit(page_size)
      .all()
    )
    rows = [
      {
        "login_datetime": row.login_datetime,
        "logout_datetime": row.logout_datetime,
        "session_duration_seconds": row.session_duration_seconds,
        "user_id": row.id,
        "name": row.name,
        "email": row.email,
        "title": row.title,
        "role": row.role_name,
        "ip_address": row.ip_address,
        "browser": row.browser,
        "browser_version": row.browser_version,
        "operating_system": row.operating_system,
        "device_type": row.device_type,
      }
      for row in results
    ]
    return rows, total

  def get_active_session(self, user_id: int) -> UserSession:
    return self.db.query(UserSession).filter(UserSession.user_id == user_id, UserSession.status == SessionStatusEnum.ACTIVE).order_by(UserSession.login_datetime.desc()).first()

  def get_session_by_token(self, token: str) -> Optional[UserSession]:
    now = datetime.now(timezone.utc)
    return (
      self.db.query(UserSession)
      .filter(
        or_(
          UserSession.session_token == token,
          and_(
            UserSession.previous_session_token == token,
            UserSession.previous_token_expires_at > now,
          ),
        )
      )
      .first()
    )

  def rotate_session_token(self, session_id, new_token: str, old_token: str, grace_seconds: int) -> int:
    grace_until = datetime.now(timezone.utc) + timedelta(seconds=grace_seconds)
    rotated = (
      self.db.query(UserSession)
      .filter(
        UserSession.id == session_id,
        UserSession.session_token == old_token,
      )
      .update(
        {
          "previous_session_token": old_token,
          "previous_token_expires_at": grace_until,
          "session_token": new_token,
        },
        synchronize_session=False,
      )
    )
    self.db.commit()
    return rotated

  def set_session_token(self, session_id, new_token: str) -> int:
    updated = (
      self.db.query(UserSession)
      .filter(UserSession.id == session_id)
      .update(
        {
          "session_token": new_token,
          "previous_session_token": None,
          "previous_token_expires_at": None,
        },
        synchronize_session=False,
      )
    )
    self.db.commit()
    return updated

  def create_user_session(self, user_session_data: dict) -> UserSession:
    user_session = UserSession(**user_session_data)
    self.db.add(user_session)
    self.db.commit()
    self.db.refresh(user_session)
    return user_session

  def update_user_session(self, user_session_data: dict):
    user_session = self.db.query(UserSession).filter(UserSession.id == user_session_data['id']).first()
    if not user_session:
      raise Exception("User session not found")
    self.db.query(UserSession).filter(UserSession.id == user_session.id).update(user_session_data)
    return self.db.query(UserSession).filter(UserSession.id == user_session_data['id']).first()

  def record_login(
    self,
    user: User,
    session_token: str,
    *,
    login_source: LoginSourceEnum = LoginSourceEnum.WEB,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    partner_id: Optional[int] = None,
    role_id: Optional[int] = None,
    browser_version: Optional[str] = None,
    operating_system: Optional[str] = None,
    device_type: Optional[str] = None,
  ) -> UserSession:
    device_type = _infer_device_type(device_type)
    browser, resolved_browser_version = _infer_browser_and_version(browser_version, user_agent)
    operating_system = _infer_operating_system(operating_system)
    if operating_system == "Unknown":
      operating_system = _infer_operating_system_from_user_agent(user_agent)

    session_data = {
      "user_id": user.id,
      "partner_id": partner_id,
      "role_id": role_id,
      "login_datetime": datetime.now(timezone.utc),
      "session_token": session_token,
      "login_source": login_source,
      "ip_address": ip_address,
      "browser": browser,
      "browser_version": resolved_browser_version,
      "operating_system": operating_system,
      "device_type": device_type,
      "user_agent": user_agent,
      "status": SessionStatusEnum.ACTIVE,
    }

    latest_active_session = self.db.query(UserSession).filter(UserSession.user_id == user.id, UserSession.status == SessionStatusEnum.ACTIVE).order_by(UserSession.login_datetime.desc()).first()
    if latest_active_session and latest_active_session.ip_address == ip_address and latest_active_session.browser == browser and latest_active_session.browser_version == resolved_browser_version and latest_active_session.operating_system == operating_system and latest_active_session.device_type == device_type:
      session_data['id'] = latest_active_session.id
      return self.update_user_session(session_data)
    else:
      return self.create_user_session(session_data)

  def logout(self, user_id: int) -> UserSession:
    user_session = self.db.query(UserSession).filter(UserSession.user_id == user_id, UserSession.status == SessionStatusEnum.ACTIVE).order_by(UserSession.login_datetime.desc()).first()
    if not user_session:
      raise Exception("User session not found")
    return self.update_user_session({
      "id": user_session.id,
      "status": SessionStatusEnum.LOGGED_OUT,
      "logout_datetime": datetime.now(timezone.utc),
      "session_duration_seconds": _get_session_duration(user_session.login_datetime, datetime.now(timezone.utc)),
    })
  
  def get_sessions_by_role(self) -> list[dict]:
    results = (self.db.query(
        Role.id,
        Role.name.label("role_name"),
        func.count(UserSession.id).label("sessions_count"),
      )
      .join(User, User.id == UserSession.user_id)
      .join(UserRole, UserRole.user_id == User.id)
      .join(Role, Role.id == UserRole.role_id)
      .group_by(Role.id)
      .order_by(func.count(UserSession.id).desc())
      .all()
    )
    return [
      {
        "role_name": row.role_name,
        "sessions_count": row.sessions_count,
      }
      for row in results
    ]


def _infer_device_type(device_type: Optional[str]) -> Optional[str]:
  if not device_type:
    return "Unknown"
  lowered = device_type.lower()
  if "mobile" in lowered or "android" in lowered or "iphone" in lowered:
    return "Mobile"
  if "tablet" in lowered or "ipad" in lowered:
    return "Tablet"
  return "Desktop"

def _infer_operating_system(operating_system: Optional[str]) -> Optional[str]:
  if not operating_system:
    return "Unknown"
  lowered = operating_system.lower()
  if "windows" in lowered:
    return "Windows"
  if "macos" in lowered:
    return "MacOS"
  if "linux" in lowered:
    return "Linux"
  return "Unknown"

def _parse_sec_ch_ua(sec_ch_ua: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
  if not sec_ch_ua:
    return None, None

  brands = re.findall(r'"([^"]+)";v="([^"]+)"', sec_ch_ua)
  brands = [
    (name, version)
    for name, version in brands
    if not name.lower().startswith("not")
  ]

  for brand_name in _SEC_CH_UA_BRANDS:
    for name, version in brands:
      if brand_name.lower() in name.lower():
        return brand_name, version

  for name, version in brands:
    if "chromium" in name.lower():
      return "Google Chrome", version

  return None, None


def _parse_user_agent(user_agent: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
  if not user_agent:
    return None, None

  for browser_name, pattern in _USER_AGENT_BROWSER_PATTERNS:
    match = pattern.search(user_agent)
    if match:
      return browser_name, match.group(1)

  return None, None


def _infer_browser_and_version(
  sec_ch_ua: Optional[str],
  user_agent: Optional[str],
) -> Tuple[str, str]:
  browser, version = _parse_sec_ch_ua(sec_ch_ua)
  if not browser or not version:
    browser, version = _parse_user_agent(user_agent)

  return browser or "Unknown", version or "Unknown"

def _infer_operating_system_from_user_agent(user_agent: Optional[str]) -> Optional[str]:
  if not user_agent:
    return "Unknown"
  lowered = user_agent.lower()
  if "windows" in lowered:
    return "Windows"
  if "macos" in lowered or "mac os" in lowered or "macintosh" in lowered:
    return "MacOS"
  if "android" in lowered:
    return "Android"
  if "iphone" in lowered or "ipad" in lowered or "ios" in lowered:
    return "iOS"
  if "linux" in lowered:
    return "Linux"
  return "Unknown"

def _infer_device_type_from_user_agent(user_agent: Optional[str]) -> Optional[str]:
  if not user_agent:
    return "Unknown"
  lowered = user_agent.lower()
  if "mobile" in lowered or "android" in lowered or "iphone" in lowered:
    return "Mobile"
  if "tablet" in lowered or "ipad" in lowered:
    return "Tablet"
  return "Desktop"

def _get_session_duration(login_datetime: datetime, logout_datetime: datetime) -> int:
  return int((logout_datetime - login_datetime).total_seconds())

def _to_utc(dt: datetime, tz: ZoneInfo) -> datetime:
  if dt.tzinfo is None:
    return dt.replace(tzinfo=tz).astimezone(timezone.utc)
  return dt.astimezone(timezone.utc)

def _format_date_label(date: datetime) -> str:
  return date.strftime("%B %d")

def _format_hour_label(hour: int) -> str:
  period = "am" if hour < 12 else "pm"
  display_hour = hour % 12 or 12
  return f"{display_hour}{period}"
