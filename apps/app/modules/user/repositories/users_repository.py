from sqlalchemy import func
from sqlalchemy.orm import Session

from apps.app.modules.user.entities.user_entity import User
from apps.app.modules.user.entities.user_session_entity import UserSession
from apps.app.utils.repositories.base_repository import BaseRepository
from apps.app.utils.datetime import DateTime
from apps.app.utils.metrics import period_change
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional
from apps.app.modules.user.repositories.user_sessions_resposity import UserSessionsRepository
from apps.app.modules.role.entities.role_entity import Role
from apps.app.modules.user.entities.user_role_entity import UserRole


class UsersTimePeriodEnum(str, Enum):
    TODAY = "TODAY"
    WEEK = "WEEK"
    MONTH = "MONTH"

class UsersRepository(BaseRepository[User]):
    def __init__(self, db: Session):
        super().__init__(db, User)

    def find_or_create(self, user_data: dict):
        email = user_data.get('email')
        if not email:
            raise ValueError('Email is required')
        user = self.db.query(User).filter_by(email=email).first()
        if user:
            return user
        user = User(**user_data)
        self.db.add(user)
        self.db.flush()
        self.db.refresh(user)
        return user
    
    def update_timezone(self, user_id: str, timezone: str) -> User:
        user = self.get_by_id(user_id)
        user.timezone = timezone
        self.db.flush()
        self.db.refresh(user)
        return user

    def get_users(self, page: int = 1, page_size: int = 10, keyword: str = "", sort_field: str = "name", sort_direction: str = "asc", role_id: Optional[int] = None) -> list[User]:
        query = (
            self.db.query(User)
            .outerjoin(UserRole, User.id == UserRole.user_id)
            .outerjoin(Role, UserRole.role_id == Role.id)
        )
        if keyword:
            query = query.filter(
                User.name.ilike(f"%{keyword}%") | User.email.ilike(f"%{keyword}%") | User.last_name.ilike(f"%{keyword}%") | User.first_name.ilike(f"%{keyword}%") |
                Role.name.ilike(f"%{keyword}%") | User.contact_number.ilike(f"%{keyword}%") | User.title.ilike(f"%{keyword}%")
            )
        if role_id:
            query = query.filter(Role.id == role_id)
        if sort_field and sort_direction:
            if sort_field == "role":
                query = query.order_by(Role.name.asc() if sort_direction == "asc" else Role.name.desc())
            else:
                query = query.order_by(getattr(User, sort_field).asc() if sort_direction == "asc" else getattr(User, sort_field).desc())
        query = query.filter(User.deleted_at.is_(None))
        users = query.offset((page - 1) * page_size).limit(page_size).all()
        total = query.count()
        return users, total
    
    def get_active_users(self, time_period: UsersTimePeriodEnum = UsersTimePeriodEnum.WEEK, user_dt: Optional[DateTime] = None) -> dict:
        user_dt = user_dt or DateTime(None)
        start_of_today = user_dt.now().replace(hour=0, minute=0, second=0, microsecond=0)
        start_of_yesterday = start_of_today - timedelta(days=1)
        start_of_this_week = start_of_today - timedelta(days=start_of_today.weekday())
        start_of_last_week = start_of_this_week - timedelta(days=7)
        start_of_this_month = start_of_today.replace(day=1)
        start_of_last_month = (start_of_this_month - timedelta(days=1)).replace(day=1)

        if time_period == UsersTimePeriodEnum.TODAY:
            period_start, previous_period_start, previous_period_end = start_of_today, start_of_yesterday, start_of_today
        elif time_period == UsersTimePeriodEnum.WEEK:
            period_start, previous_period_start, previous_period_end = start_of_this_week, start_of_last_week, start_of_this_week
        elif time_period == UsersTimePeriodEnum.MONTH:
            period_start, previous_period_start, previous_period_end = start_of_this_month, start_of_last_month, start_of_this_month
        else:
            raise ValueError(f"Invalid time period: {time_period}")

        period_start_utc = user_dt.to_utc(period_start)
        previous_period_start_utc = user_dt.to_utc(previous_period_start)
        previous_period_end_utc = user_dt.to_utc(previous_period_end)

        count = self.db.query(User).join(UserSession).filter(UserSession.login_datetime >= period_start_utc).distinct(User.id).count()
        previous_count = self.db.query(User).join(UserSession).filter(UserSession.login_datetime >= previous_period_start_utc, UserSession.login_datetime < previous_period_end_utc).distinct(User.id).count()
        return {"count": count, **period_change(count, previous_count)}
    def get_average_login_per_user(self) -> float:
        user_sessions_repository = UserSessionsRepository(self.db)
        total_users = self.total_count()
        total_login_count = user_sessions_repository.get_total_sessions()
        if total_users == 0:
            return 0
        return total_login_count / total_users
    
    def get_average_login_duration(self, days: int = 30) -> float:
        start_of_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days)
        return self.db.query(UserSession).filter(UserSession.login_datetime >= start_of_date).avg(UserSession.session_duration_seconds)
    
    def get_top_active_users(self, days: int = 30) -> list[dict]:
        days_ago = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days)
        total_session_duration = func.coalesce(func.sum(UserSession.session_duration_seconds), 0)

        results = (
            self.db.query(
                User.id,
                User.name,
                User.title,
                total_session_duration.label("total_session_duration_seconds"),
                func.count(UserSession.id).label("login_count"),
                func.max(UserSession.login_datetime).label("last_login"),
            )
            .join(UserSession, User.id == UserSession.user_id)
            .filter(UserSession.login_datetime >= days_ago)
            .group_by(User.id, User.name)
            .order_by(func.count(UserSession.id).desc(), User.name.asc())
            .limit(10)
            .all()
        )

        top_active_users = [
            {
                "user_id": row.id,
                "name": row.name,
                "total_session_duration_seconds": int(row.total_session_duration_seconds),
                "login_count": row.login_count,
                "title": row.title,
                "last_login": row.last_login.isoformat() if row.last_login else None,
            }
            for row in results
        ]
        return top_active_users

    def soft_delete_user(self, user_id: int):
        user = self.get_by_id(user_id)
        if not user:
            return None
        user.deleted_at = datetime.now()
        self.db.flush()
        self.db.refresh(user)
        return user
    
