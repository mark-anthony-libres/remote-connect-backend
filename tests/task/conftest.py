import apps.app.celery_app  # noqa: F401
import pytest

from apps.app.modules.task.entities.task_run_entity import TaskRunEntity
from database.session_factory import SessionLocal


@pytest.fixture
def task_run_ids():
    ids: list[str] = []
    yield ids
    if not ids:
        return
    session = SessionLocal()
    try:
        session.query(TaskRunEntity).filter(TaskRunEntity.id.in_(ids)).delete(synchronize_session=False)
        session.commit()
    finally:
        session.close()
