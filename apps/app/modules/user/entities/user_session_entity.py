import enum

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func

from apps.app.utils.decorators.entity import Entity
from database.entities.base import Base


class LoginSourceEnum(str, enum.Enum):
  WEB = "Web"
  MOBILE = "Mobile"
  API = "API"


class SessionStatusEnum(str, enum.Enum):
  ACTIVE = "Active"
  LOGGED_OUT = "Logged Out"
  EXPIRED = "Expired"


LOGIN_SOURCE_ENUM = sa.Enum(
  LoginSourceEnum,
  name="login_source",
  values_callable=lambda enum_cls: [member.value for member in enum_cls],
  create_type=True,
)

SESSION_STATUS_ENUM = sa.Enum(
  SessionStatusEnum,
  name="session_status",
  values_callable=lambda enum_cls: [member.value for member in enum_cls],
  create_type=True,
)


@Entity()
class UserSession(Base):
  __tablename__ = "tblt_user_sessions"

  id = sa.Column(
    UUID(as_uuid=True),
    primary_key=True,
    server_default=sa.text("gen_random_uuid()"),
  )
  user_id = sa.Column(
    sa.Integer,
    sa.ForeignKey("tblm_users.id", ondelete="CASCADE"),
    nullable=False,
    index=True,
  )
  partner_id = sa.Column(sa.Integer, nullable=True)
  role_id = sa.Column(sa.Integer, nullable=True)

  login_datetime = sa.Column(sa.DateTime(timezone=True), nullable=False)
  logout_datetime = sa.Column(sa.DateTime(timezone=True), nullable=True)
  session_duration_seconds = sa.Column(sa.Integer, nullable=True)
  session_token = sa.Column(sa.Text, nullable=False, unique=True)
  previous_session_token = sa.Column(sa.Text, nullable=True)
  previous_token_expires_at = sa.Column(sa.DateTime(timezone=True), nullable=True)

  login_source = sa.Column(LOGIN_SOURCE_ENUM, nullable=True)
  ip_address = sa.Column(sa.Text, nullable=True)
  browser = sa.Column(sa.Text, nullable=True)
  browser_version = sa.Column(sa.Text, nullable=True)
  operating_system = sa.Column(sa.Text, nullable=True)
  device_type = sa.Column(sa.Text, nullable=True)
  status = sa.Column(SESSION_STATUS_ENUM, nullable=True)
  user_agent = sa.Column(sa.Text, nullable=True)

  created_at = sa.Column(
    sa.DateTime(timezone=True), nullable=False, server_default=func.now()
  )
  updated_at = sa.Column(
    sa.DateTime(timezone=True),
    nullable=False,
    server_default=func.now(),
    onupdate=func.now(),
  )
