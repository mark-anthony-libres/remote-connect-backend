import random
import uuid
from datetime import datetime, timedelta, timezone

from faker import Faker
from sqlalchemy.orm import Session

from apps.app.modules.role.entities.role_entity import Role
from apps.app.modules.user.entities.user_entity import User
from apps.app.modules.user.entities.user_session_entity import (
    LoginSourceEnum,
    SessionStatusEnum,
    UserSession,
)

BROWSERS = ["Chrome", "Firefox", "Safari", "Edge"]
BROWSER_VERSIONS = ["120.0", "121.0", "122.0", "123.0", "17.0", "18.0"]
OPERATING_SYSTEMS = ["Windows", "MacOS", "Linux"]
DEVICE_TYPES = ["Desktop", "Mobile", "Tablet"]

faker = Faker()


def _seed_users(session: Session, count: int = 10) -> list[User]:
    users = []
    for _ in range(count):
        first_name = faker.first_name()
        last_name = faker.last_name()
        users.append(
            User(
                name=f"{first_name} {last_name}",
                email=faker.unique.email(),
                first_name=first_name,
                last_name=last_name,
                is_active=True,
                title=faker.job(),
            )
        )
    session.add_all(users)
    session.flush()
    for user in users:
        session.refresh(user)
    return users


def _seed_user_sessions(
    session: Session, users: list[User], sessions_per_user: int = 3
) -> list[UserSession]:
    user_sessions = []
    now = datetime.now(timezone.utc)

    for user in users:
        for _ in range(random.randint(1, sessions_per_user)):
            days_ago = random.randint(0, 30)
            login_datetime = now - timedelta(
                days=days_ago,
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59),
            )
            status = random.choices(
                [
                    SessionStatusEnum.ACTIVE,
                    SessionStatusEnum.LOGGED_OUT,
                    SessionStatusEnum.EXPIRED,
                ],
                weights=[0.3, 0.5, 0.2],
            )[0]

            logout_datetime = None
            session_duration_seconds = None
            if status != SessionStatusEnum.ACTIVE:
                duration_minutes = random.randint(5, 180)
                logout_datetime = login_datetime + timedelta(minutes=duration_minutes)
                session_duration_seconds = duration_minutes * 60

            user_sessions.append(
                UserSession(
                    user_id=user.id,
                    session_token=str(uuid.uuid4()),
                    login_datetime=login_datetime,
                    logout_datetime=logout_datetime,
                    session_duration_seconds=session_duration_seconds,
                    login_source=random.choice(list(LoginSourceEnum)),
                    ip_address=faker.ipv4(),
                    browser=random.choice(BROWSERS),
                    browser_version=random.choice(BROWSER_VERSIONS),
                    operating_system=random.choice(OPERATING_SYSTEMS),
                    device_type=random.choice(DEVICE_TYPES),
                    status=status,
                )
            )

    session.add_all(user_sessions)
    session.flush()
    return user_sessions


def _seed_roles(session: Session) -> list[Role]:
    roles = [
        Role(name="Admin", description="Admin role"),
        Role(name="Regular User", description="Regular user role"),
    ]
    session.add_all(roles)
    session.flush()
    return roles


def _seed_users_with_roles(session: Session, roles: list[Role]) -> list[User]:
    users = session.query(User).all()
    for user in users:
        if user.name == "Decypher Dev":
            user.role_id = roles[0].id
        else:
            user.role_id = random.choice(roles).id
        session.add(user)
    session.flush()
    return users


def main(session: Session) -> None:
    users = _seed_users(session)
    roles = _seed_roles(session)
    _seed_users_with_roles(session, roles)
    _seed_user_sessions(session, users)
