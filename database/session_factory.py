
from __future__ import annotations

import os
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from apps.app.core.db import _database_url
from apps.app.core.settings import settings


def bck_database_url() -> str:
    db_name = settings.pg_db_name
    db_user = settings.pg_db_user
    db_password = settings.pg_db_password
    db_host = settings.pg_db_host
    db_port = settings.pg_db_port
    return f"postgresql+psycopg2://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"


_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(_database_url(), pool_pre_ping=True)
    return _engine



SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, autocommit=False)

# Context manager for DB session
from contextlib import contextmanager

@contextmanager
def SessionFactory():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_session():
    return SessionFactory
