
from apps.app.modules.impersonation.entities.impersonation_sandbox_record_entity import (
    ImpersonationSandboxRecord,
)


def set_value(self, name: str, value: int) -> dict:
    record = self.session.query(ImpersonationSandboxRecord).filter_by(name=name).one_or_none()
    if record is None:
        record = ImpersonationSandboxRecord(name=name, value=value)
        self.session.add(record)
    else:
        record.value = value
    self.session.flush()
    return {"id": record.id, "name": record.name, "value": record.value, "session_identity": id(self.session)}


def get_value(self, name: str):
    record = self.session.query(ImpersonationSandboxRecord).filter_by(name=name).one_or_none()
    return record.value if record else None


def get_session_identity(self) -> int:
    return id(self.session)


def set_value_then_raise(self, name: str, value: int) -> None:
    self.session.add(ImpersonationSandboxRecord(name=name, value=value))
    self.session.flush()
    raise RuntimeError("deliberate failure to prove rollback/close-out behavior")


def nested_set_value(self, name: str, value: int) -> dict:
    from apps.app.core import services

    outer_session_identity = id(self.session)
    inner_result = services.call(set_value, name, value)
    return {"outer_session_identity": outer_session_identity, "inner_result": inner_result}


def misbehaving_service_opens_second_session(self, name: str, value: int) -> dict:
    from sqlalchemy import text

    self.session.add(ImpersonationSandboxRecord(name=name, value=value))
    self.session.flush()

    from database.session_factory import get_session

    with get_session()() as rogue_session:
        rogue_session.execute(text("SELECT 1"))
    return {"should_not_reach_here": True}


def misbehaving_service_uses_bare_repository(self) -> dict:
    from apps.app.modules.role.repositories.role_repository import RoleRepository

    repository = RoleRepository()
    repository.get_by_id(1)
    return {"should_not_reach_here": True}
