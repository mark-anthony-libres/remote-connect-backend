import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import text

from apps.app.core import db_guard
from database.session_factory import SessionLocal
from apps.app.modules.impersonation.entities.impersonation_audit_entity import (
    ImpersonationAudit,
)
from apps.app.modules.impersonation.entities.impersonation_sandbox_record_entity import (
    ImpersonationSandboxRecord,
)
from apps.app.modules.impersonation.service import impersonation_lock as lock
from apps.app.modules.impersonation.service import impersonation_session_holder as holder

logger = logging.getLogger(__name__)


@db_guard.DBAllowNewSession()
def _save_audit_entry(impersonation_id: str, **fields) -> None:
    session = SessionLocal()
    try:
        audit = (
            session.query(ImpersonationAudit)
            .filter_by(impersonation_id=impersonation_id)
            .one_or_none()
        )
        if audit is None:
            if "admin_user_id" not in fields:
                return
            audit = ImpersonationAudit(impersonation_id=impersonation_id)
            session.add(audit)
        for key, value in fields.items():
            setattr(audit, key, value)
        session.commit()
    finally:
        session.close()


def end_impersonation(active_impersonation: lock.ActiveImpersonation, reason: str) -> None:
    if holder.has_session(active_impersonation.impersonation_id):
        with holder.use_session(active_impersonation.impersonation_id) as (session, _started_at):
            session.rollback()
        holder.end_session()

    _save_audit_entry(
        active_impersonation.impersonation_id,
        ended_at=datetime.now(timezone.utc),
        termination_reason=reason,
        status="ended",
    )

    lock.release_impersonation(active_impersonation.impersonation_id)

    from apps.app.websocket.emitter import invalidate_endpoint_sync

    invalidate_endpoint_sync("impersonation/state")

    if reason != "explicit_logout":
        from apps.app.websocket.emitter import invalidate_impersonation_sync

        invalidate_impersonation_sync(active_impersonation.impersonation_id)


def _is_session_stale(held_impersonation_id: Optional[str]) -> bool:
    if held_impersonation_id is None:
        return False

    active = lock.get_active_impersonation()
    active_exists = active is not None
    lease_alive = None

    if not active_exists:
        stale, reason = True, "redis_active_missing"
    elif active.impersonation_id != held_impersonation_id:
        stale, reason = True, "redis_active_replaced"
    else:
        lease_alive = lock.is_worker_alive()
        stale = not lease_alive
        reason = "lease_expired" if stale else "healthy"

    logger.info(
        "impersonation stale-session check: impersonation_id=%s redis_active_exists=%s "
        "lease_alive=%s stale=%s reason=%s",
        held_impersonation_id, active_exists, lease_alive, stale, reason,
    )
    return stale


def cleanup_stale_session() -> bool:
    return holder.end_session_if_stale(_is_session_stale)


def start_impersonation(admin_user_id: int, target_user_id: int, ttl_seconds: int) -> dict:
    ttl_seconds = max(1, min(ttl_seconds, lock.IMPERSONATION_MAX_DURATION_SECONDS))
    impersonation_id = str(uuid.uuid4())
    active_impersonation = lock.ActiveImpersonation(
        impersonation_id=impersonation_id,
        admin_user_id=admin_user_id,
        target_user_id=target_user_id,
        started_at=time.time(),
        ttl_seconds=ttl_seconds,
    )

    cleanup_stale_session()

    claimed, replaced_impersonation = lock.try_claim_impersonation(active_impersonation)
    if not claimed:
        raise HTTPException(
            status_code=409,
            detail=(
                "Another impersonation session is already active. It must be logged "
                "out or expire before a new one can start."
            ),
        )

    if replaced_impersonation is not None:
        _save_audit_entry(
            replaced_impersonation.impersonation_id,
            ended_at=datetime.now(timezone.utc),
            termination_reason="worker_crash_detected",
            status="ended",
        )
        holder.end_session()

    holder.start_session(impersonation_id)

    _save_audit_entry(
        impersonation_id,
        admin_user_id=admin_user_id,
        target_user_id=target_user_id,
        started_at=datetime.now(timezone.utc),
        ended_at=None,
        termination_reason=None,
        status="active",
    )

    with holder.use_session(impersonation_id) as (session, started_at):
        info = _build_impersonation_info(session, active_impersonation, started_at)
    info["reclaimed_stale_previous_session"] = replaced_impersonation is not None
    return info


def _check_ownership(impersonation_id: str, admin_user_id: int) -> lock.ActiveImpersonation:
    active_impersonation = lock.get_active_impersonation()
    if active_impersonation is None or active_impersonation.impersonation_id != impersonation_id:
        raise HTTPException(status_code=404, detail="No active impersonation session with that id.")
    if active_impersonation.admin_user_id != admin_user_id:
        raise HTTPException(
            status_code=403,
            detail="This impersonation session belongs to a different administrator.",
        )
    return active_impersonation


def verify_impersonation(impersonation_id: str, admin_user_id: int) -> lock.ActiveImpersonation:
    active_impersonation = _check_ownership(impersonation_id, admin_user_id)

    if lock.is_expired(active_impersonation):
        end_impersonation(active_impersonation, reason="expired")
        raise HTTPException(status_code=410, detail="Impersonation session has expired (3-hour maximum).")

    if not lock.check_and_refresh_worker_heartbeat():
        end_impersonation(active_impersonation, reason="worker_crash_detected")
        raise HTTPException(
            status_code=410,
            detail="Impersonation session was lost - its owning worker is no longer alive.",
        )

    return active_impersonation


def _handle_session_vanished(active_impersonation: lock.ActiveImpersonation):
    end_impersonation(active_impersonation, reason="worker_crash_detected")
    raise HTTPException(
        status_code=410,
        detail="Impersonation session was lost - its owning worker is no longer alive.",
    )


def handle_session_busy():
    raise HTTPException(
        status_code=503,
        detail=(
            "The impersonation session is temporarily busy handling another "
            "request - please try again shortly."
        ),
    )


def update_record(impersonation_id: str, admin_user_id: int, name: str, value: int) -> dict:
    active_impersonation = verify_impersonation(impersonation_id, admin_user_id)
    try:
        with holder.use_session(impersonation_id) as (session, started_at):
            record = (
                session.query(ImpersonationSandboxRecord).filter_by(name=name).one_or_none()
            )
            if record is None:
                record = ImpersonationSandboxRecord(name=name, value=value)
                session.add(record)
            else:
                record.value = value
            session.flush()
            return _build_impersonation_info(session, active_impersonation, started_at)
    except TimeoutError:
        handle_session_busy()
    except holder.ImpersonationSessionNotFoundError:
        _handle_session_vanished(active_impersonation)
    except Exception:
        end_impersonation(active_impersonation, reason="request_error")
        raise


def adjust_record(impersonation_id: str, admin_user_id: int, name: str, delta: int) -> dict:
    active_impersonation = verify_impersonation(impersonation_id, admin_user_id)
    try:
        with holder.use_session(impersonation_id) as (session, started_at):
            record = (
                session.query(ImpersonationSandboxRecord).filter_by(name=name).one_or_none()
            )
            if record is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No sandbox record named '{name}' yet - call /update first.",
                )
            record.value = record.value + delta
            session.flush()
            return _build_impersonation_info(session, active_impersonation, started_at)
    except TimeoutError:
        handle_session_busy()
    except holder.ImpersonationSessionNotFoundError:
        _handle_session_vanished(active_impersonation)
    except HTTPException:
        raise
    except Exception:
        end_impersonation(active_impersonation, reason="request_error")
        raise


def get_impersonation_info(impersonation_id: str, admin_user_id: int) -> dict:
    active_impersonation = verify_impersonation(impersonation_id, admin_user_id)
    try:
        with holder.use_session(impersonation_id) as (session, started_at):
            return _build_impersonation_info(session, active_impersonation, started_at)
    except TimeoutError:
        handle_session_busy()
    except holder.ImpersonationSessionNotFoundError:
        _handle_session_vanished(active_impersonation)


def get_impersonation_status_for_admin(admin_user_id: int) -> dict:
    active_impersonation = lock.get_active_impersonation()
    if active_impersonation is None or active_impersonation.admin_user_id != admin_user_id:
        raise HTTPException(status_code=404, detail="No active impersonation session for this admin.")

    if lock.is_expired(active_impersonation):
        end_impersonation(active_impersonation, reason="expired")
        raise HTTPException(status_code=410, detail="Impersonation session has expired (3-hour maximum).")

    if not lock.is_worker_alive():
        raise HTTPException(
            status_code=410,
            detail="Impersonation session was lost - its owning worker is no longer alive.",
        )

    from database.session_factory import get_session
    from apps.app.modules.user.repositories.users_repository import UsersRepository

    with get_session()() as session:
        repo = UsersRepository(session)
        admin_user = repo.get_by_id(active_impersonation.admin_user_id)
        target_user = repo.get_by_id(active_impersonation.target_user_id)

    heartbeat_seconds_remaining = lock.lease_seconds_remaining()
    return {
        "impersonation_id": active_impersonation.impersonation_id,
        "admin_user_id": active_impersonation.admin_user_id,
        "admin_name": admin_user.name if admin_user else None,
        "target_user_id": active_impersonation.target_user_id,
        "target_name": target_user.name if target_user else None,
        "started_at": datetime.fromtimestamp(active_impersonation.started_at, tz=timezone.utc).isoformat(),
        "ttl_seconds": active_impersonation.ttl_seconds,
        "seconds_remaining": lock.seconds_remaining(active_impersonation),
        "heartbeat_seconds_remaining": heartbeat_seconds_remaining,
        "heartbeat_seconds_ago": max(0, lock.IMPERSONATION_LEASE_SECONDS - heartbeat_seconds_remaining),
    }


def force_end_impersonation(admin_user_id: int) -> dict:
    active_impersonation = lock.get_active_impersonation()
    if active_impersonation is None or active_impersonation.admin_user_id != admin_user_id:
        raise HTTPException(status_code=404, detail="No active impersonation session for this admin.")

    end_impersonation(active_impersonation, reason="force_ended_by_admin")
    return {"impersonation_id": active_impersonation.impersonation_id, "status": "ended"}


def logout(impersonation_id: str, admin_user_id: int) -> dict:
    active_impersonation = _check_ownership(impersonation_id, admin_user_id)
    end_impersonation(active_impersonation, reason="explicit_logout")
    return {"impersonation_id": impersonation_id, "status": "rolled_back"}


@db_guard.DBAllowNewSession()
def reissue_admin_token(admin_id: int, admin_session_id: str) -> Optional[str]:
    from apps.app.modules.okta.service.okta_service import OktaService
    from apps.app.modules.user.repositories.users_repository import UsersRepository
    from apps.app.modules.user.repositories.user_sessions_resposity import UserSessionsRepository
    from database.session_factory import get_session

    with get_session()() as session:
        admin_user = UsersRepository(session).get_by_id(admin_id)
        if admin_user is None or not admin_user.is_active:
            return None
        new_admin_token = OktaService.create_new_token(admin_user)["token"]
        UserSessionsRepository(session).set_session_token(
            uuid.UUID(admin_session_id), new_admin_token
        )
        return new_admin_token


def _build_impersonation_info(session, active_impersonation: lock.ActiveImpersonation, started_at) -> dict:
    from apps.app.modules.user.repositories.users_repository import UsersRepository

    backend_pid = session.execute(text("SELECT pg_backend_pid()")).scalar()
    records = session.execute(
        text("SELECT id, name, value FROM tblm_impersonation_sandbox_records ORDER BY name")
    ).fetchall()
    users_repo = UsersRepository(session)
    admin_user = users_repo.get_by_id(active_impersonation.admin_user_id)
    target_user = users_repo.get_by_id(active_impersonation.target_user_id)
    heartbeat_seconds_remaining = lock.lease_seconds_remaining()
    return {
        "impersonation_id": active_impersonation.impersonation_id,
        "admin_user_id": active_impersonation.admin_user_id,
        "admin_name": admin_user.name if admin_user else None,
        "target_user_id": active_impersonation.target_user_id,
        "target_name": target_user.name if target_user else None,
        "started_at": datetime.fromtimestamp(active_impersonation.started_at, tz=timezone.utc).isoformat(),
        "worker_pid": holder.worker_pid(),
        "session_identity": id(session),
        "postgres_backend_pid": backend_pid,
        "in_transaction": session.in_transaction(),
        "transaction_started_at": started_at.isoformat() if started_at else None,
        "ttl_seconds": active_impersonation.ttl_seconds,
        "seconds_remaining": lock.seconds_remaining(active_impersonation),
        "heartbeat_seconds_remaining": heartbeat_seconds_remaining,
        "heartbeat_seconds_ago": max(0, lock.IMPERSONATION_LEASE_SECONDS - heartbeat_seconds_remaining),
        "sandbox_records": [
            {"id": r.id, "name": r.name, "value": r.value} for r in records
        ],
    }
