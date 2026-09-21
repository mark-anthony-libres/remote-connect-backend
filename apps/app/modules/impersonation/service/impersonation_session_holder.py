import logging
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from apps.app.core.db import _database_url

logger = logging.getLogger(__name__)

_engine = create_engine(_database_url(), pool_size=1, max_overflow=0, pool_pre_ping=True)
_ImpersonationSessionLocal = sessionmaker(bind=_engine, autoflush=False, autocommit=False)

_session_lock = threading.Lock()
_impersonation_session: Optional[Session] = None
_impersonation_id: Optional[str] = None
_started_at: Optional[datetime] = None


class ImpersonationSessionNotFoundError(Exception):
    pass


def start_session(impersonation_id: str) -> None:
    global _impersonation_session, _impersonation_id, _started_at
    with _session_lock:
        if _impersonation_session is not None:
            raise RuntimeError("This worker is already holding an impersonation Session.")
        _impersonation_session = _ImpersonationSessionLocal()
        _impersonation_id = impersonation_id
        _started_at = datetime.now(timezone.utc)


@contextmanager
def use_session(impersonation_id: str):
    if not _session_lock.acquire(timeout=30):
        raise TimeoutError("Timed out waiting to use the impersonation Session.")
    try:
        if _impersonation_session is None or _impersonation_id != impersonation_id:
            raise ImpersonationSessionNotFoundError(
                "No matching impersonation Session is held by this worker."
            )
        yield _impersonation_session, _started_at
    finally:
        _session_lock.release()


def _end_session_locked() -> None:
    global _impersonation_session, _impersonation_id, _started_at
    if _impersonation_session is not None:
        try:
            _impersonation_session.rollback()
        finally:
            _impersonation_session.close()
    _impersonation_session = None
    _impersonation_id = None
    _started_at = None


def end_session() -> None:
    with _session_lock:
        _end_session_locked()


def end_session_if_stale(is_stale: Callable[[Optional[str]], bool]) -> bool:
    if not _session_lock.acquire(blocking=False):
        logger.info(
            "impersonation stale-session cleanup skipped: Session is currently in use by a request"
        )
        return False
    try:
        if _impersonation_session is None:
            return False
        held_id = _impersonation_id
        if not is_stale(held_id):
            return False
        logger.info(
            "impersonation stale-session cleanup closing Session: impersonation_id=%s", held_id
        )
        _end_session_locked()
        return True
    finally:
        _session_lock.release()


def has_session(impersonation_id: str) -> bool:
    with _session_lock:
        return _impersonation_session is not None and _impersonation_id == impersonation_id


def worker_pid() -> int:
    return os.getpid()
