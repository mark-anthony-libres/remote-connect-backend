
import functools
import inspect
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Optional

from sqlalchemy import event
from sqlalchemy.pool import Pool

from apps.app.core.services import _current_impersonation_id

_checkout_budget: ContextVar[Optional[int]] = ContextVar("db_guard_checkout_budget", default=None)

_new_session_allowed: ContextVar[bool] = ContextVar("db_guard_new_session_allowed", default=False)

_installed = False


class DatabaseSessionBypassError(RuntimeError):
    pass


def _checkout_listener(dbapi_connection, connection_record, connection_proxy) -> None:
    impersonation_id = _current_impersonation_id.get()
    if impersonation_id is None:
        return

    if _new_session_allowed.get():
        return

    budget = _checkout_budget.get()
    if not budget:
        raise DatabaseSessionBypassError(
            "Database Session creation is not allowed during impersonation. "
            "Use services.call() and self.session, or explicitly opt in with "
            "@DBAllowNewSession()."
        )
    _checkout_budget.set(budget - 1)


def install() -> None:
    global _installed
    if _installed:
        return
    event.listen(Pool, "checkout", _checkout_listener)
    _installed = True


@contextmanager
def exempt_one_checkout():
    previous = _checkout_budget.get()
    token = _checkout_budget.set((previous or 0) + 1)
    try:
        yield
    finally:
        _checkout_budget.reset(token)


def DBAllowNewSession() -> Callable:
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            token = _new_session_allowed.set(True)
            try:
                return await func(*args, **kwargs)
            finally:
                _new_session_allowed.reset(token)

        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            token = _new_session_allowed.set(True)
            try:
                return func(*args, **kwargs)
            finally:
                _new_session_allowed.reset(token)

        return async_wrapper if inspect.iscoroutinefunction(func) else sync_wrapper
    return decorator
