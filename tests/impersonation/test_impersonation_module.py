from __future__ import annotations

import time

import pytest
from fastapi import HTTPException

from apps.app.modules.impersonation.controller import impersonation_controller as controller
from apps.app.modules.impersonation.entities.impersonation_audit_entity import (
    ImpersonationAudit,
)
from apps.app.modules.impersonation.entities.impersonation_sandbox_record_entity import (
    ImpersonationSandboxRecord,
)
from apps.app.modules.impersonation.service import impersonation_lock as lock
from apps.app.modules.impersonation.service import impersonation_session_holder as holder
from apps.app.modules.impersonation.service import impersonation_service as service
from apps.app.utils.redis import get_redis_init
from database.session_factory import SessionLocal

ADMIN_A = 90001
ADMIN_B = 90002
TARGET_USER = 90101


@pytest.fixture(autouse=True)
def clean_impersonation_state():
    _force_reset()
    yield
    _force_reset()


def _force_reset():
    holder.end_session()
    with get_redis_init() as r:
        r.delete(lock.IMPERSONATION_ACTIVE_KEY)
        r.delete(lock.IMPERSONATION_LEASE_KEY)
    session = SessionLocal()
    try:
        session.query(ImpersonationSandboxRecord).delete()
        session.query(ImpersonationAudit).delete()
        session.commit()
    finally:
        session.close()


def _read_committed_record(name: str):
    session = SessionLocal()
    try:
        return session.query(ImpersonationSandboxRecord).filter_by(name=name).one_or_none()
    finally:
        session.close()


def _read_audit(impersonation_id: str) -> ImpersonationAudit:
    session = SessionLocal()
    try:
        return (
            session.query(ImpersonationAudit)
            .filter_by(impersonation_id=impersonation_id)
            .one()
        )
    finally:
        session.close()


def test_start_impersonation_succeeds():
    result = service.start_impersonation(admin_user_id=ADMIN_A, target_user_id=TARGET_USER, ttl_seconds=3600)

    assert result["admin_user_id"] == ADMIN_A
    assert result["target_user_id"] == TARGET_USER
    assert result["in_transaction"] is True

    active_impersonation = lock.get_active_impersonation()
    assert active_impersonation is not None
    assert active_impersonation.admin_user_id == ADMIN_A

    audit = _read_audit(result["impersonation_id"])
    assert audit.status == "active"
    assert audit.admin_user_id == ADMIN_A


def test_second_admin_is_rejected_while_active():
    first = service.start_impersonation(admin_user_id=ADMIN_A, target_user_id=TARGET_USER, ttl_seconds=3600)

    with pytest.raises(HTTPException) as exc_info:
        service.start_impersonation(admin_user_id=ADMIN_B, target_user_id=TARGET_USER, ttl_seconds=3600)
    assert exc_info.value.status_code == 409

    active_impersonation = lock.get_active_impersonation()
    assert active_impersonation is not None
    assert active_impersonation.impersonation_id == first["impersonation_id"]
    assert active_impersonation.admin_user_id == ADMIN_A


def test_multiple_requests_reuse_same_session_and_transaction():
    start = service.start_impersonation(admin_user_id=ADMIN_A, target_user_id=TARGET_USER, ttl_seconds=3600)
    imp_id = start["impersonation_id"]

    r1 = service.update_record(imp_id, ADMIN_A, "counter", 10)
    r2 = service.update_record(imp_id, ADMIN_A, "counter", 20)
    r3 = service.get_impersonation_info(imp_id, ADMIN_A)

    assert r1["worker_pid"] == r2["worker_pid"] == r3["worker_pid"]
    assert r1["session_identity"] == r2["session_identity"] == r3["session_identity"]
    assert r1["postgres_backend_pid"] == r2["postgres_backend_pid"] == r3["postgres_backend_pid"]

    with pytest.raises(holder.ImpersonationSessionNotFoundError):
        with holder.use_session("some-other-impersonation-id"):
            pass


def test_flush_makes_changes_visible_inside_transaction():
    start = service.start_impersonation(admin_user_id=ADMIN_A, target_user_id=TARGET_USER, ttl_seconds=3600)
    imp_id = start["impersonation_id"]

    service.update_record(imp_id, ADMIN_A, "balance", 100)
    after_second = service.adjust_record(imp_id, ADMIN_A, "balance", 50)

    balance = next(r for r in after_second["sandbox_records"] if r["name"] == "balance")
    assert balance["value"] == 150


def test_changes_not_committed_during_impersonation():
    start = service.start_impersonation(admin_user_id=ADMIN_A, target_user_id=TARGET_USER, ttl_seconds=3600)
    imp_id = start["impersonation_id"]

    service.update_record(imp_id, ADMIN_A, "not_yet_real", 999)

    assert _read_committed_record("not_yet_real") is None


def test_logout_rolls_everything_back():
    start = service.start_impersonation(admin_user_id=ADMIN_A, target_user_id=TARGET_USER, ttl_seconds=3600)
    imp_id = start["impersonation_id"]

    service.update_record(imp_id, ADMIN_A, "will_vanish", 200)
    assert _read_committed_record("will_vanish") is None

    service.logout(imp_id, ADMIN_A)

    assert _read_committed_record("will_vanish") is None
    assert lock.get_active_impersonation() is None
    assert lock.is_worker_alive() is False

    audit = _read_audit(imp_id)
    assert audit.status == "ended"
    assert audit.termination_reason == "explicit_logout"
    assert audit.ended_at is not None


def test_expiration_rolls_everything_back():
    start = service.start_impersonation(admin_user_id=ADMIN_A, target_user_id=TARGET_USER, ttl_seconds=1)
    imp_id = start["impersonation_id"]
    service.update_record(imp_id, ADMIN_A, "expiring", 42)

    time.sleep(1.2)

    with pytest.raises(HTTPException) as exc_info:
        service.get_impersonation_info(imp_id, ADMIN_A)
    assert exc_info.value.status_code == 410

    assert _read_committed_record("expiring") is None
    assert lock.get_active_impersonation() is None

    audit = _read_audit(imp_id)
    assert audit.status == "ended"
    assert audit.termination_reason == "expired"


def test_another_admin_cannot_access_or_control_the_session():
    start = service.start_impersonation(admin_user_id=ADMIN_A, target_user_id=TARGET_USER, ttl_seconds=3600)
    imp_id = start["impersonation_id"]

    with pytest.raises(HTTPException) as exc_info:
        service.get_impersonation_info(imp_id, ADMIN_B)
    assert exc_info.value.status_code == 403

    with pytest.raises(HTTPException) as exc_info:
        service.update_record(imp_id, ADMIN_B, "hijacked", 1)
    assert exc_info.value.status_code == 403

    with pytest.raises(HTTPException) as exc_info:
        service.logout(imp_id, ADMIN_B)
    assert exc_info.value.status_code == 403

    active_impersonation = lock.get_active_impersonation()
    assert active_impersonation is not None
    assert active_impersonation.impersonation_id == imp_id


def test_cleanup_occurs_after_request_failure():
    start = service.start_impersonation(admin_user_id=ADMIN_A, target_user_id=TARGET_USER, ttl_seconds=3600)
    imp_id = start["impersonation_id"]

    with pytest.raises(Exception):
        service.update_record(imp_id, ADMIN_A, None, 1)

    assert lock.get_active_impersonation() is None
    audit = _read_audit(imp_id)
    assert audit.status == "ended"
    assert audit.termination_reason == "request_error"


def test_lock_is_released_after_termination():
    start = service.start_impersonation(admin_user_id=ADMIN_A, target_user_id=TARGET_USER, ttl_seconds=3600)
    service.logout(start["impersonation_id"], ADMIN_A)

    assert lock.get_active_impersonation() is None
    assert lock.is_worker_alive() is False


def test_new_admin_can_start_after_previous_ends():
    first = service.start_impersonation(admin_user_id=ADMIN_A, target_user_id=TARGET_USER, ttl_seconds=3600)
    service.logout(first["impersonation_id"], ADMIN_A)

    second = service.start_impersonation(admin_user_id=ADMIN_B, target_user_id=TARGET_USER, ttl_seconds=3600)
    assert second["admin_user_id"] == ADMIN_B
    assert second["impersonation_id"] != first["impersonation_id"]


def test_stale_heartbeat_is_reclaimed_as_worker_crash():
    first = service.start_impersonation(admin_user_id=ADMIN_A, target_user_id=TARGET_USER, ttl_seconds=3600)
    first_id = first["impersonation_id"]

    with get_redis_init() as r:
        r.delete(lock.IMPERSONATION_LEASE_KEY)

    holder.end_session()

    second = service.start_impersonation(admin_user_id=ADMIN_B, target_user_id=TARGET_USER, ttl_seconds=3600)
    assert second["impersonation_id"] != first_id

    old_audit = _read_audit(first_id)
    assert old_audit.status == "ended"
    assert old_audit.termination_reason == "worker_crash_detected"


def test_dedicated_worker_gate_rejects_requests_outside_the_pinned_worker(monkeypatch):
    monkeypatch.delenv(controller.DEDICATED_WORKER_ENV, raising=False)
    with pytest.raises(Exception):
        controller._require_dedicated_worker()

    monkeypatch.setenv(controller.DEDICATED_WORKER_ENV, "1")
    controller._require_dedicated_worker()
