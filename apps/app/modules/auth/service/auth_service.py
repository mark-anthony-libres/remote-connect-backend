from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy.orm import Session

from apps.app.core.auth.tokens import decode_token, TokenError
from apps.app.core.auth.access_token import is_impersonation_worker
from apps.app.core.db import session_factory
from apps.app.modules.impersonation.service import impersonation_lock
from apps.app.modules.user.entities.user_entity import User
from apps.app.modules.user.entities.user_session_entity import SessionStatusEnum, UserSession
from apps.app.modules.user.repositories.users_repository import UsersRepository
from apps.app.modules.user.repositories.user_sessions_resposity import UserSessionsRepository


@dataclass
class ImpersonationInfo:
    admin_id: int
    impersonation_id: str
    admin_session_id: str


@dataclass
class AuthenticatedSession:
    user: User
    session: Optional[UserSession]
    payload: dict
    impersonation: Optional[ImpersonationInfo] = None


def _authenticate_normal_user(token: str, payload: dict, db_session: Session) -> AuthenticatedSession:
    user_id = payload.get("sub")
    if not user_id:
        raise TokenError("Token is missing a subject")

    user = UsersRepository(db_session).get_by_id(user_id)
    if not user or not user.is_active:
        raise TokenError("User not found or inactive")

    session = UserSessionsRepository(db_session).get_session_by_token(token)
    if not session or session.status == SessionStatusEnum.LOGGED_OUT:
        raise TokenError("Session has been logged out")

    return AuthenticatedSession(user=user, session=session, payload=payload)


def _authenticate_impersonation(
    payload: dict, db_session: Session, impersonation_id_header: Optional[str]
) -> AuthenticatedSession:
    if not is_impersonation_worker():
        raise TokenError(
            "Impersonation tokens are only valid on the dedicated impersonation worker."
        )

    impersonation_id = payload.get("impersonation_id")
    admin_id = payload.get("admin_id")
    target_user_id = payload.get("sub")
    admin_session_id = payload.get("admin_session_id")
    if not impersonation_id or not admin_id or not target_user_id or not admin_session_id:
        raise TokenError("Impersonation token is missing required claims")

    if not impersonation_id_header:
        raise TokenError("X-Impersonation-ID header is required for an impersonation request.")
    if impersonation_id_header != impersonation_id:
        raise TokenError("X-Impersonation-ID does not match the authenticated impersonation.")

    active = impersonation_lock.get_active_impersonation()
    if active is None or active.impersonation_id != impersonation_id:
        raise TokenError("This impersonation is no longer active")
    if str(active.admin_user_id) != str(admin_id):
        raise TokenError("Impersonation token does not belong to the admin who started it")
    if str(active.target_user_id) != str(target_user_id):
        raise TokenError("Impersonation token does not match its target user")

    admin_user = UsersRepository(db_session).get_by_id(admin_id)
    if not admin_user or not admin_user.is_admin:
        raise TokenError("The admin who started this impersonation is no longer an administrator")

    user = UsersRepository(db_session).get_by_id(target_user_id)
    if not user or not user.is_active:
        raise TokenError("Target user not found or inactive")

    impersonation_lock.refresh_worker_heartbeat()

    return AuthenticatedSession(
        user=user,
        session=None,
        payload=payload,
        impersonation=ImpersonationInfo(
            admin_id=int(admin_id), impersonation_id=impersonation_id, admin_session_id=admin_session_id
        ),
    )


def _authenticate_with_session(
    token: str, db_session: Session, impersonation_id_header: Optional[str] = None
) -> AuthenticatedSession:
    payload = decode_token(token)

    if payload.get("impersonated") is True:
        return _authenticate_impersonation(payload, db_session, impersonation_id_header)

    if impersonation_id_header:
        raise TokenError(
            "X-Impersonation-ID was sent, but this access_token is not an impersonation token."
        )

    return _authenticate_normal_user(token, payload, db_session)


def authenticate(
    token: str, db: Session | None = None, impersonation_id_header: Optional[str] = None
) -> AuthenticatedSession:
    owns_session = db is None
    db_session = db or session_factory()
    try:
        return _authenticate_with_session(token, db_session, impersonation_id_header)
    finally:
        if owns_session:
            db_session.close()


def verify_token(context, token: str, impersonation_id_header: Optional[str] = None) -> AuthenticatedSession:
    result = _authenticate_with_session(token, context.session, impersonation_id_header)
    context.session.expunge(result.user)
    if result.session is not None:
        context.session.expunge(result.session)
    return result


def logout(context, token: str) -> tuple[int, Optional[object]]:
    payload = decode_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise TokenError("Token is missing a subject")

    user_id = int(user_id)

    if is_impersonation_worker():
        impersonation_id = payload.get("impersonation_id")
        admin_id = payload.get("admin_id")
        if impersonation_id and admin_id:
            try:
                from apps.app.modules.impersonation.service import impersonation_service
                impersonation_service.logout(impersonation_id=impersonation_id, admin_user_id=int(admin_id))
            except Exception as e:
                from apps.app.utils import log_exception_with_traceback
                log_exception_with_traceback(e, context="Failed to end impersonation during /auth/logout")
        return user_id, None

    session = UserSessionsRepository(context.session).logout(user_id)

    from apps.app.utils.run_async import run_async
    from apps.app.websocket.emitter import invalidate_session
    run_async(invalidate_session(str(session.id)))

    return user_id, session.id
