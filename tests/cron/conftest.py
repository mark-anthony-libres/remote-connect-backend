import pytest

from apps.app.utils.task_concurrency import GLOBAL_SLOT_PREFIX, MAX_RUNNING_TASKS, build_task_lock_key
from apps.app.utils.redis import redis_delete


def _clean_all_slots() -> None:
    for index in range(MAX_RUNNING_TASKS + 2):
        redis_delete(f"{GLOBAL_SLOT_PREFIX}:{index}")


@pytest.fixture
def clean_redis_slots():
    _clean_all_slots()
    yield
    _clean_all_slots()


@pytest.fixture
def ensure_clean_lock_key():
    keys_to_clean = []

    def _ensure_clean(task_name: str, tracking_key: str) -> str:
        key = build_task_lock_key(task_name, tracking_key)
        redis_delete(key)
        keys_to_clean.append(key)
        return key

    yield _ensure_clean

    for key in keys_to_clean:
        redis_delete(key)
