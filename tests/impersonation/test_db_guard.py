from __future__ import annotations

import pytest
from sqlalchemy import text

from apps.app.modules.impersonation.entities.impersonation_audit_entity import (
    ImpersonationAudit,
)
from apps.app.modules.impersonation.entities.impersonation_sandbox_record_entity import (
    ImpersonationSandboxRecord,
)
from apps.app.core import db_guard
from apps.app.core import services
from apps.app.modules.impersonation.service import impersonation_lock as lock
from apps.app.modules.impersonation.service import impersonation_provider
from apps.app.modules.impersonation.service import impersonation_session_holder as holder
from apps.app.modules.impersonation.service import impersonation_service as imp_service
from apps.app.modules.impersonation.service import services_demo
from apps.app.utils.redis import get_redis_init
from database.session_factory import SessionLocal, get_session

ADMIN_A = 92001
USER_C = 92002
TARGET_USER = 92101

db_guard.install()
impersonation_provider.install()


@pytest.fixture(autouse=True)
def clean_state():
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


def _start_impersonation(admin_id: int = ADMIN_A) -> str:
    return imp_service.start_impersonation(
        admin_user_id=admin_id, target_user_id=TARGET_USER, ttl_seconds=3600
    )["impersonation_id"]


def test_normal_request_allows_get_session():
    with get_session()() as session:
        assert session.execute(text("SELECT 1")).scalar() == 1


def test_impersonation_request_allows_the_approved_session():
    imp_id = _start_impersonation()
    with services.RequestContext(ADMIN_A, imp_id):
        result = services.call(services_demo.set_value, "approved", 1)
    assert result["value"] == 1


def test_controller_bypass_is_blocked_during_impersonation():
    imp_id = _start_impersonation()
    with services.RequestContext(ADMIN_A, imp_id):
        with pytest.raises(db_guard.DatabaseSessionBypassError):
            with get_session()() as session:
                session.execute(text("SELECT 1"))


def test_service_creating_a_second_session_is_blocked():
    imp_id = _start_impersonation()
    with services.RequestContext(ADMIN_A, imp_id):
        with pytest.raises(db_guard.DatabaseSessionBypassError):
            services.call(services_demo.misbehaving_service_opens_second_session, "x", 1)


def test_repository_creating_its_own_session_is_blocked():
    imp_id = _start_impersonation()
    with services.RequestContext(ADMIN_A, imp_id):
        with pytest.raises(db_guard.DatabaseSessionBypassError):
            services.call(services_demo.misbehaving_service_uses_bare_repository)


def test_different_normal_user_is_unaffected_by_someone_elses_impersonation():
    _start_impersonation(admin_id=ADMIN_A)

    with services.RequestContext(USER_C, None):
        with get_session()() as session:
            assert session.execute(text("SELECT 1")).scalar() == 1


def test_nested_calls_reuse_same_session_under_the_guard():
    imp_id = _start_impersonation()
    with services.RequestContext(ADMIN_A, imp_id):
        result = services.call(services_demo.nested_set_value, "nested", 7)
    assert result["outer_session_identity"] == result["inner_result"]["session_identity"]


def test_no_second_checkout_allowed_during_a_legitimate_call():
    imp_id = _start_impersonation()
    with services.RequestContext(ADMIN_A, imp_id):
        with pytest.raises(db_guard.DatabaseSessionBypassError):
            services.call(services_demo.misbehaving_service_opens_second_session, "y", 2)
        with pytest.raises(db_guard.DatabaseSessionBypassError):
            services.call(services_demo.misbehaving_service_uses_bare_repository)


def test_service_context_cannot_be_constructed_directly():
    with pytest.raises(RuntimeError):
        services.ServiceContext(SessionLocal())
