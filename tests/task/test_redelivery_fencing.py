from __future__ import annotations

import uuid

import apps.app.celery_app  # noqa: F401
from apps.app.celery_app import celery_app
from apps.app.modules.task.entities.task_run_entity import TaskRunStatusEnum
from apps.app.modules.task.repositories.task_run_repository import TaskRunRepository
from apps.app.utils.decorators.task_decorator import task
from database.session_factory import SessionLocal


def _get_status(task_id: str) -> TaskRunStatusEnum:
    session = SessionLocal()
    try:
        return TaskRunRepository(session).get_task(task_id).status
    finally:
        session.close()


def test_try_start_claims_a_task_id_with_no_row_yet(task_run_ids):
    task_id = str(uuid.uuid4())
    task_run_ids.append(task_id)

    session = SessionLocal()
    try:
        claimed = TaskRunRepository(session).try_start(task_id, task_name="tests.fake", tag=None)
    finally:
        session.close()

    assert claimed is True, "no existing row is a legitimate first execution, not a duplicate"
    assert _get_status(task_id) == TaskRunStatusEnum.RUNNING


def test_try_start_claims_an_existing_queued_row(task_run_ids):
    task_id = str(uuid.uuid4())
    task_run_ids.append(task_id)

    session = SessionLocal()
    try:
        repo = TaskRunRepository(session)
        repo.create_task_run(task_id, task_name="tests.fake")
        claimed = repo.try_start(task_id, task_name="tests.fake", tag=None)
    finally:
        session.close()

    assert claimed is True
    assert _get_status(task_id) == TaskRunStatusEnum.RUNNING


def test_try_start_rejects_a_second_call_for_the_same_task_id(task_run_ids):
    task_id = str(uuid.uuid4())
    task_run_ids.append(task_id)

    session = SessionLocal()
    try:
        repo = TaskRunRepository(session)
        first = repo.try_start(task_id, task_name="tests.fake", tag=None)
        second = repo.try_start(task_id, task_name="tests.fake", tag=None)
    finally:
        session.close()

    assert first is True
    assert second is False, "a second claim attempt on the same task_id is a redelivery/duplicate, not fresh work"


def test_try_start_rejects_a_task_id_that_already_reached_a_terminal_state(task_run_ids):
    task_id = str(uuid.uuid4())
    task_run_ids.append(task_id)

    session = SessionLocal()
    try:
        repo = TaskRunRepository(session)
        repo.try_start(task_id, task_name="tests.fake", tag=None)
        repo.mark_success(task_id)
        claimed_again = repo.try_start(task_id, task_name="tests.fake", tag=None)
    finally:
        session.close()

    assert claimed_again is False
    assert _get_status(task_id) == TaskRunStatusEnum.SUCCESS, "a rejected claim must not touch the existing row"


def test_create_task_run_after_try_start_does_not_clobber_the_running_state(task_run_ids):
    task_id = str(uuid.uuid4())
    task_run_ids.append(task_id)

    session = SessionLocal()
    try:
        repo = TaskRunRepository(session)
        repo.try_start(task_id, task_name="tests.fake", tag=None)
        repo.create_task_run(task_id, task_name="tests.fake")
    finally:
        session.close()

    assert _get_status(task_id) == TaskRunStatusEnum.RUNNING, (
        "the late-arriving enqueue-time write must not reset an already-claimed row back to QUEUED"
    )


def _run_eagerly(dispatch_fn):
    original_eager = celery_app.conf.task_always_eager
    original_propagates = celery_app.conf.task_eager_propagates
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    try:
        dispatch_fn()
    finally:
        celery_app.conf.task_always_eager = original_eager
        celery_app.conf.task_eager_propagates = original_propagates


def test_redeliver_false_task_never_runs_its_body_twice_for_the_same_task_id(task_run_ids):
    calls = []

    @task()
    def fenced_probe_task():
        calls.append(1)
        return "done"

    task_id = str(uuid.uuid4())
    task_run_ids.append(task_id)

    def dispatch_twice():
        fenced_probe_task.apply_async(task_id=task_id)
        fenced_probe_task.apply_async(task_id=task_id)

    _run_eagerly(dispatch_twice)

    assert calls == [1], "the second delivery of an already-started task_id must never run the body again"


def test_redeliver_true_task_is_not_fenced_and_reruns_normally(task_run_ids):
    calls = []

    @task(redeliver=True)
    def unfenced_probe_task():
        calls.append(1)
        return "done"

    task_id = str(uuid.uuid4())
    task_run_ids.append(task_id)

    def dispatch_twice():
        unfenced_probe_task.apply_async(task_id=task_id)
        unfenced_probe_task.apply_async(task_id=task_id)

    _run_eagerly(dispatch_twice)

    assert calls == [1, 1], "redeliver=True must skip the fencing check entirely - unchanged, original behavior"
