from __future__ import annotations

import uuid

from apps.app.celery_app import celery_app
from apps.app.utils.decorators.analysis import _interval_seconds, analysis
from apps.app.utils.redis import redis_delete
from apps.app.utils.task_concurrency import build_task_lock_key


class _FakeAsyncResult:
    def __init__(self, task_id: str):
        self.id = task_id


def test_interval_seconds_converts_all_supported_units():
    assert _interval_seconds({"seconds": 30}) == 30
    assert _interval_seconds({"minutes": 2}) == 120
    assert _interval_seconds({"hours": 1}) == 3600
    assert _interval_seconds({"days": 1}) == 86400
    assert _interval_seconds({"weeks": 1}) == 7 * 86400
    assert _interval_seconds({"milliseconds": 500}) == 0.5
    assert _interval_seconds({"hours": 2, "minutes": 30}) == 2 * 3600 + 30 * 60
    assert _interval_seconds({}) == 0


def test_direct_job_registers_the_original_function_unwrapped():
    def sample_direct_job():
        pass

    decorated = analysis(interval={"seconds": 60}, name="sample direct", direct=True)(sample_direct_job)

    assert getattr(decorated, "__wrapped__", None) is sample_direct_job
    assert decorated._celery_task is None
    assert decorated._is_analysis is True


def test_default_job_wraps_the_function_into_a_locked_celery_dispatch():
    def sample_default_job():
        pass

    decorated = analysis(interval={"seconds": 60}, name="sample default")(sample_default_job)

    assert decorated is not sample_default_job
    assert getattr(decorated, "__wrapped__", None) is sample_default_job
    assert decorated._celery_task is not None
    assert hasattr(decorated._celery_task, "delay")


def test_default_job_disables_celery_redelivery_unless_opted_in():
    def sample_no_redeliver_job():
        pass

    def sample_redeliver_job():
        pass

    default_job = analysis(interval={"seconds": 60}, name="no redeliver by default")(sample_no_redeliver_job)
    opted_in_job = analysis(interval={"seconds": 60}, name="redeliver opt-in", redeliver=True)(sample_redeliver_job)

    assert default_job._celery_task.acks_late is False, (
        "redeliver defaults to False, which must map to acks_late=False so a "
        "crashed worker never gets this task redelivered by Celery"
    )
    assert opted_in_job._celery_task.acks_late is True, (
        "redeliver=True must map to acks_late=True to opt back into Celery's "
        "normal at-least-once redelivery"
    )


def test_default_job_dispatches_exactly_once_while_a_run_is_in_flight(monkeypatch):
    def sample_locked_job():
        pass

    decorated = analysis(interval={"milliseconds": 1}, name="dedup sample")(sample_locked_job)
    task = decorated._celery_task
    lock_key = build_task_lock_key(task.name, task.__task_metadata_key__)

    redis_delete(lock_key)
    redis_delete(task.__task_metadata_key__)

    apply_async_call_count = 0

    def fake_apply_async(*args, **kwargs):
        nonlocal apply_async_call_count
        apply_async_call_count += 1
        return _FakeAsyncResult(kwargs.get("task_id") or str(uuid.uuid4()))

    monkeypatch.setattr(task, "apply_async", fake_apply_async)

    try:
        decorated()
        decorated()

        assert apply_async_call_count == 1, "second call while the lock is still held must be skipped"
    finally:
        redis_delete(lock_key)


def test_default_job_actually_runs_the_body_to_completion_when_due(clean_redis_slots):
    def sample_eager_job():
        calls.append("ran")
        return "done"

    calls: list[str] = []

    decorated = analysis(interval={"seconds": 3600}, name="eager sample")(sample_eager_job)
    task = decorated._celery_task
    lock_key = build_task_lock_key(task.name, task.__task_metadata_key__)

    redis_delete(lock_key)
    redis_delete(task.__task_metadata_key__)

    original_eager = celery_app.conf.task_always_eager
    original_propagates = celery_app.conf.task_eager_propagates
    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True

    try:
        decorated()

        assert calls == ["ran"], "a due job must actually execute its body, not just get enqueued"
    finally:
        celery_app.conf.task_always_eager = original_eager
        celery_app.conf.task_eager_propagates = original_propagates
        redis_delete(lock_key)


def test_direct_job_runs_its_body_immediately_with_no_locking():
    calls = []

    def sample_direct_job():
        calls.append(1)

    decorated = analysis(interval={"seconds": 60}, name="sample direct", direct=True)(sample_direct_job)

    decorated()
    decorated()

    assert calls == [1, 1], "direct=True jobs run every call, unthrottled by any lock"
