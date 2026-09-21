from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import apps.app.celery_app  # noqa: F401
from celery.app.task import _task_stack

from apps.app.modules.task.analysis import task_watchdog_analysis as watchdog_module
from apps.app.modules.task.entities.task_run_entity import TaskRunEntity, TaskRunStatusEnum
from apps.app.modules.task.repositories.task_run_repository import TaskRunRepository
from database.session_factory import SessionLocal

detect_abandoned_task_runs = watchdog_module.detect_abandoned_task_runs


def _create_task_run(task_id: str, status: TaskRunStatusEnum, age: timedelta) -> None:
    created_at = datetime.now(timezone.utc) - age
    session = SessionLocal()
    try:
        session.add(
            TaskRunEntity(
                id=uuid.UUID(task_id),
                task_name="tests.task.fake_task",
                status=status,
                created_at=created_at,
                started_at=created_at if status == TaskRunStatusEnum.RUNNING else None,
            )
        )
        session.commit()
    finally:
        session.close()


def _get_status(task_id: str) -> TaskRunStatusEnum:
    session = SessionLocal()
    try:
        return TaskRunRepository(session).get_task(task_id).status
    finally:
        session.close()


def test_marks_an_abandoned_running_task_as_interrupted(monkeypatch, task_run_ids):
    task_id = str(uuid.uuid4())
    task_run_ids.append(task_id)
    _create_task_run(task_id, TaskRunStatusEnum.RUNNING, age=timedelta(minutes=20))

    monkeypatch.setattr(watchdog_module, "get_live_celery_task_ids", lambda: set())

    detect_abandoned_task_runs.__wrapped__()

    assert _get_status(task_id) == TaskRunStatusEnum.INTERRUPTED


def test_does_not_touch_a_task_that_is_still_actually_active(monkeypatch, task_run_ids):
    task_id = uuid.uuid4().hex
    task_run_ids.append(task_id)
    _create_task_run(task_id, TaskRunStatusEnum.RUNNING, age=timedelta(minutes=20))

    monkeypatch.setattr(watchdog_module, "get_live_celery_task_ids", lambda: {task_id})

    detect_abandoned_task_runs.__wrapped__()

    assert _get_status(task_id) == TaskRunStatusEnum.RUNNING


def test_does_not_touch_anything_when_worker_inspection_fails(monkeypatch, task_run_ids):
    task_id = str(uuid.uuid4())
    task_run_ids.append(task_id)
    _create_task_run(task_id, TaskRunStatusEnum.RUNNING, age=timedelta(minutes=20))

    monkeypatch.setattr(watchdog_module, "get_live_celery_task_ids", lambda: None)

    detect_abandoned_task_runs.__wrapped__()

    assert _get_status(task_id) == TaskRunStatusEnum.RUNNING, (
        "a temporary inspection failure must never be treated as proof "
        "that every in-flight task is dead"
    )


def test_ignores_rows_still_within_the_grace_period(monkeypatch, task_run_ids):
    task_id = str(uuid.uuid4())
    task_run_ids.append(task_id)
    _create_task_run(task_id, TaskRunStatusEnum.RUNNING, age=timedelta(seconds=5))

    monkeypatch.setattr(watchdog_module, "get_live_celery_task_ids", lambda: set())

    detect_abandoned_task_runs.__wrapped__()

    assert _get_status(task_id) == TaskRunStatusEnum.RUNNING


def test_detects_an_abandoned_queued_task_too(monkeypatch, task_run_ids):
    task_id = str(uuid.uuid4())
    task_run_ids.append(task_id)
    _create_task_run(task_id, TaskRunStatusEnum.QUEUED, age=timedelta(minutes=20))

    monkeypatch.setattr(watchdog_module, "get_live_celery_task_ids", lambda: set())

    detect_abandoned_task_runs.__wrapped__()

    assert _get_status(task_id) == TaskRunStatusEnum.INTERRUPTED


def test_multiple_abandoned_tasks_are_all_interrupted_in_one_pass(monkeypatch, task_run_ids):
    task_ids = [str(uuid.uuid4()) for _ in range(3)]
    task_run_ids.extend(task_ids)
    for task_id in task_ids:
        _create_task_run(task_id, TaskRunStatusEnum.RUNNING, age=timedelta(minutes=20))

    monkeypatch.setattr(watchdog_module, "get_live_celery_task_ids", lambda: set())

    detect_abandoned_task_runs.__wrapped__()

    assert all(_get_status(task_id) == TaskRunStatusEnum.INTERRUPTED for task_id in task_ids)


def test_watchdog_does_not_interrupt_its_own_in_flight_row(monkeypatch, task_run_ids):
    self_task_id = uuid.uuid4().hex
    task_run_ids.append(self_task_id)
    _create_task_run(self_task_id, TaskRunStatusEnum.RUNNING, age=timedelta(minutes=20))

    monkeypatch.setattr(watchdog_module, "get_live_celery_task_ids", lambda: set())

    watchdog_task = detect_abandoned_task_runs._celery_task
    _task_stack.push(watchdog_task)
    watchdog_task.push_request(id=self_task_id)
    try:
        detect_abandoned_task_runs.__wrapped__()
    finally:
        watchdog_task.pop_request()
        _task_stack.pop()

    assert _get_status(self_task_id) == TaskRunStatusEnum.RUNNING, (
        "the watchdog must never mark its own currently-executing task_run row as interrupted"
    )
