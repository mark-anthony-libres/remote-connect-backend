from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest

from apps.app.utils.task_concurrency import (
    GLOBAL_SLOT_PREFIX,
    MAX_RUNNING_TASKS,
    TaskScheduler,
    release_execution_slot,
    reserve_task_slot,
    unlock_task_execution,
)
from apps.app.utils.redis import redis_delete, redis_delete_if_value_matches, redis_get
from tests.cron.fakes import FakeAsyncResult, FakeCeleryTask, FakeTrackingSource


def _finish_task_execution(task_id: str) -> None:
    release_execution_slot(task_id)
    unlock_task_execution(task_id)


def _release_claimed_slot(slot_key: str, slot_token: str) -> None:
    redis_delete_if_value_matches(slot_key, slot_token)


def test_concurrent_triggers_are_skipped_while_a_run_is_active(ensure_clean_lock_key):
    task_name = "sync.cron.demo"
    tracking_key = "demo-tracker"
    task_a = FakeCeleryTask(name=task_name, task_id="task-A")
    tracking = FakeTrackingSource(tracking_key)
    ensure_clean_lock_key(task_name, tracking_key)

    assert TaskScheduler.run_if_due_interval(1, task_a, tracking_source=tracking), \
        "Sync A should have been allowed to run"
    assert not TaskScheduler.run_if_due_interval(1000, task_a, tracking_source=tracking), \
        "Sync B should have been skipped while A is still processing"
    assert not TaskScheduler.run_if_due_interval(1000, task_a, tracking_source=tracking), \
        "Sync C should have been skipped while A is still processing"

    _finish_task_execution(task_a.task_id)

    tracking.backdate_last_enqueued_at(timedelta(hours=1))

    task_d = FakeCeleryTask(name=task_name, task_id="task-D")
    assert TaskScheduler.run_if_due_interval(1, task_d, tracking_source=tracking), \
        "Sync D should have been allowed to run once A finished"

    _finish_task_execution(task_d.task_id)

    assert task_a.delay_call_count == 1
    assert task_d.delay_call_count == 1


def test_simultaneous_acquires_have_exactly_one_winner(ensure_clean_lock_key):
    lock_key = ensure_clean_lock_key("concurrency.race", "race-tracker")
    attempts = 25

    with ThreadPoolExecutor(max_workers=attempts) as pool:
        tokens = list(pool.map(lambda _: TaskScheduler.try_lock_task(lock_key), range(attempts)))

    winners = [token for token in tokens if token is not None]
    assert len(winners) == 1, f"expected exactly 1 winner out of {attempts} concurrent attempts, got {len(winners)}"

    TaskScheduler.unlock_task(lock_key, winners[0])


def test_stale_lock_owner_cannot_reclaim_a_lock_it_no_longer_holds(ensure_clean_lock_key):
    lock_key = ensure_clean_lock_key("concurrency.stale-owner", "stale-tracker")

    token_a = TaskScheduler.try_lock_task(lock_key)
    assert token_a is not None

    redis_delete(lock_key)
    token_b = TaskScheduler.try_lock_task(lock_key)
    assert token_b is not None

    TaskScheduler.unlock_task(lock_key, token_a)

    assert redis_get(lock_key) == token_b, "B's lock must survive A's stale release"

    TaskScheduler.unlock_task(lock_key, token_b)


def test_slot_pool_caps_concurrency_and_reclaims_on_release(clean_redis_slots):
    claimed_slots = [reserve_task_slot() for _ in range(MAX_RUNNING_TASKS)]
    assert all(slot_key is not None for slot_key, _ in claimed_slots), \
        "expected all MAX_RUNNING_TASKS slots to be claimable"

    overflow_slot_key, _ = reserve_task_slot()
    assert overflow_slot_key is None, "no slot should remain once MAX_RUNNING_TASKS are claimed"

    slot_key, slot_token = claimed_slots[0]
    _release_claimed_slot(slot_key, slot_token)
    freed_slot_key, freed_slot_token = reserve_task_slot()
    assert freed_slot_key == slot_key, "releasing one slot should free exactly one for reuse"

    _release_claimed_slot(freed_slot_key, freed_slot_token)
    for slot_key, slot_token in claimed_slots[1:]:
        _release_claimed_slot(slot_key, slot_token)


def test_failed_enqueue_releases_its_lock_and_slot(clean_redis_slots, ensure_clean_lock_key):
    task_name = "concurrency.enqueue-failure"
    tracking_key = "enqueue-failure-tracker"
    lock_key = ensure_clean_lock_key(task_name, tracking_key)
    task = FakeCeleryTask(name=task_name, raises=ConnectionError("broker unreachable"))
    tracking = FakeTrackingSource(tracking_key)

    with pytest.raises(ConnectionError):
        TaskScheduler.run_if_due_interval(1, task, tracking_source=tracking)

    assert redis_get(lock_key) is None, "lock must not leak when delay() raises"
    assert redis_get(f"{GLOBAL_SLOT_PREFIX}:0") is None, "slot must not leak when delay() raises"


def test_lock_and_slot_are_bound_to_the_task_id_before_dispatch_not_after(
    clean_redis_slots, ensure_clean_lock_key
):
    task_name = "concurrency.instant-completion"
    tracking_key = "instant-completion-tracker"
    lock_key = ensure_clean_lock_key(task_name, tracking_key)
    tracking = FakeTrackingSource(tracking_key)

    class InstantlyCompletingTask:
        name = task_name

        def apply_async(self, args=None, kwargs=None, task_id=None, **options):
            release_execution_slot(task_id)
            unlock_task_execution(task_id)
            return FakeAsyncResult(task_id)

    was_due = TaskScheduler.run_if_due_interval(1, InstantlyCompletingTask(), tracking_source=tracking)

    assert was_due is True
    assert redis_get(lock_key) is None, (
        "the lock must already be bound to the task_id before dispatch, so an "
        "instantly-completing task's own cleanup can find and release it"
    )
    assert redis_get(f"{GLOBAL_SLOT_PREFIX}:0") is None, "same as above, for the slot"
