from contextlib import AbstractContextManager
from contextvars import ContextVar
from typing import Any, Callable, Optional, Protocol

from fastapi import HTTPException

from database.session_factory import SessionLocal


_construction_token = object()


class ServiceContext:

    def __init__(self, session, _token=None):
        if _token is not _construction_token:
            raise RuntimeError("ServiceContext must be created by services.call(), not directly.")
        self.session = session


_current_admin_id: ContextVar[Optional[int]] = ContextVar("current_admin_id", default=None)
_current_impersonation_id: ContextVar[Optional[str]] = ContextVar(
    "current_impersonation_id", default=None
)
_current_context: ContextVar[Optional[ServiceContext]] = ContextVar(
    "current_service_context", default=None
)


class RequestContext:

    def __init__(self, admin_id: int, impersonation_id: Optional[str] = None):
        self.admin_id = admin_id
        self.impersonation_id = impersonation_id
        self._admin_token = None
        self._impersonation_token = None

    def __enter__(self) -> "RequestContext":
        self._admin_token = _current_admin_id.set(self.admin_id)
        self._impersonation_token = _current_impersonation_id.set(self.impersonation_id)
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        _current_admin_id.reset(self._admin_token)
        _current_impersonation_id.reset(self._impersonation_token)


class ImpersonationSessionProvider(Protocol):

    def begin(self, impersonation_id: str, admin_id: Optional[int]) -> Any:
        ...

    def session_scope(self, active: Any) -> AbstractContextManager:
        ...

    def fail(self, active: Any) -> None:
        ...


_impersonation_provider: Optional[ImpersonationSessionProvider] = None


def register_impersonation_provider(provider: ImpersonationSessionProvider) -> None:
    global _impersonation_provider
    _impersonation_provider = provider


def call(service: Callable, *args, **kwargs) -> Any:
    outer = _current_context.get()
    if outer is not None:
        return service(outer, *args, **kwargs)

    impersonation_id = _current_impersonation_id.get()

    if impersonation_id:
        if _impersonation_provider is None:
            raise RuntimeError(
                "An impersonation_id is active for this request but no impersonation "
                "session provider is registered - the module implementing impersonation "
                "was never imported (see register_impersonation_provider())."
            )
        admin_id = _current_admin_id.get()
        active = _impersonation_provider.begin(impersonation_id, admin_id)

        try:
            with _impersonation_provider.session_scope(active) as session:
                context = ServiceContext(session, _token=_construction_token)
                token = _current_context.set(context)
                try:
                    result = service(context, *args, **kwargs)
                    session.flush()
                    return result
                finally:
                    _current_context.reset(token)
        except HTTPException:
            raise
        except Exception:
            _impersonation_provider.fail(active)
            raise

    session = SessionLocal()
    context = ServiceContext(session, _token=_construction_token)
    token = _current_context.set(context)
    try:
        result = service(context, *args, **kwargs)
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        _current_context.reset(token)
        session.close()
