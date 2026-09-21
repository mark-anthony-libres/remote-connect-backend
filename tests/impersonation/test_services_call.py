from __future__ import annotations

from sqlalchemy.orm import Session as SASession

from apps.app.modules.impersonation.entities.impersonation_audit_entity import (
    ImpersonationAudit,
)
from apps.app.modules.impersonation.entities.impersonation_sandbox_record_entity import (
    ImpersonationSandboxRecord,
)
from apps.app.modules.impersonation.service import impersonation_lock as lock
from apps.app.modules.impersonation.service import impersonation_provider
from apps.app.modules.impersonation.service import impersonation_session_holder as holder
from apps.app.modules.impersonation.service import impersonation_service as imp_service
from apps.app.core import services
from apps.app.modules.impersonation.service import services_demo
from apps.app.utils.redis import get_redis_init
from database.session_factory import SessionLocal

import pytest

ADMIN_A = 91001
ADMIN_B = 91002
TARGET_USER = 91101

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


def _read_committed_value(name: str):
    session = SessionLocal()
    try:
        record = session.query(ImpersonationSandboxRecord).filter_by(name=name).one_or_none()
        return record.value if record else None
    finally:
        session.close()


def _start_impersonation(admin_id: int = ADMIN_A) -> str:
    return imp_service.start_impersonation(
        admin_user_id=admin_id, target_user_id=TARGET_USER, ttl_seconds=3600
    )["impersonation_id"]


def test_normal_calls_get_a_fresh_session(monkeypatch):
    committed_sessions = []
    original_commit = SASession.commit

    def counting_commit(self, *args, **kwargs):
        committed_sessions.append(self)
        return original_commit(self, *args, **kwargs)

    monkeypatch.setattr(SASession, "commit", counting_commit)

    services.call(services_demo.get_session_identity)
    services.call(services_demo.get_session_identity)

    assert len(committed_sessions) == 2
    assert committed_sessions[0] is not committed_sessions[1]


def test_normal_calls_commit():
    services.call(services_demo.set_value, "commit_test", 42)
    assert _read_committed_value("commit_test") == 42


def test_normal_failures_rollback():
    with pytest.raises(RuntimeError):
        services.call(services_demo.set_value_then_raise, "rollback_test", 99)
    assert _read_committed_value("rollback_test") is None


def test_impersonation_calls_reuse_same_session_across_requests():
    imp_id = _start_impersonation()

    with services.RequestContext(ADMIN_A, imp_id):
        first = services.call(services_demo.get_session_identity)
        second = services.call(services_demo.get_session_identity)

    assert first == second
    assert holder.has_session(imp_id)


def test_impersonation_calls_only_flush():
    imp_id = _start_impersonation()

    with services.RequestContext(ADMIN_A, imp_id):
        services.call(services_demo.set_value, "imp_only_flush", 100)
        assert services.call(services_demo.get_value, "imp_only_flush") == 100

    assert _read_committed_value("imp_only_flush") is None


def test_nested_calls_reuse_same_session():
    result = services.call(services_demo.nested_set_value, "nested_test", 55)
    assert result["outer_session_identity"] == result["inner_result"]["session_identity"]
    assert _read_committed_value("nested_test") == 55


def test_nested_calls_do_not_independently_commit(monkeypatch):
    commit_calls = []
    original_commit = SASession.commit

    def counting_commit(self, *args, **kwargs):
        commit_calls.append(id(self))
        return original_commit(self, *args, **kwargs)

    monkeypatch.setattr(SASession, "commit", counting_commit)

    services.call(services_demo.nested_set_value, "nested_commit_count", 5)

    assert len(commit_calls) == 1


def test_nested_impersonation_calls_do_not_deadlock():
    imp_id = _start_impersonation()

    with services.RequestContext(ADMIN_A, imp_id):
        outer_identity = services.call(services_demo.get_session_identity)
        result = services.call(services_demo.nested_set_value, "nested_imp_test", 77)

    assert result["outer_session_identity"] == outer_identity
    assert result["inner_result"]["session_identity"] == outer_identity
    assert _read_committed_value("nested_imp_test") is None


def test_different_requests_remain_isolated():
    imp_id = _start_impersonation(admin_id=ADMIN_A)

    with services.RequestContext(ADMIN_A, imp_id):
        impersonated_identity = services.call(services_demo.get_session_identity)

    with services.RequestContext(ADMIN_B, None):
        normal_identity = services.call(services_demo.get_session_identity)

    assert normal_identity != impersonated_identity

    default_identity = services.call(services_demo.get_session_identity)
    assert default_identity != impersonated_identity
