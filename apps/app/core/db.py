from __future__ import annotations

import os
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from apps.app.core.settings import settings

from apps.app.core.env import load_project_env


load_project_env()


def _database_url() -> str:
    db = settings.pg_db_name
    user = settings.pg_db_user
    password = settings.pg_db_password
    host = settings.pg_db_host
    port = settings.pg_db_port
    return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}"


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return create_engine(_database_url(), pool_pre_ping=True, future=True)


@lru_cache(maxsize=1)
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, autocommit=False, future=True)


def session_factory() -> Session:
    return get_sessionmaker()()
