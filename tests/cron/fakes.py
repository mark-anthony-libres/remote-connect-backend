from __future__ import annotations

from datetime import datetime, timedelta, timezone


class FakeAsyncResult:
    def __init__(self, task_id: str):
        self.id = task_id


class FakeCeleryTask:
    def __init__(self, name: str, task_id: str = "fake-task-id", raises: Exception | None = None):
        self.name = name
        self.task_id = task_id
        self._raises = raises
        self.delay_call_count = 0

    def delay(self, *args, **kwargs):
        return self.apply_async(args=args, kwargs=kwargs)

    def apply_async(self, args=None, kwargs=None, task_id=None, **options):
        self.delay_call_count += 1
        if task_id is not None:
            self.task_id = task_id
        if self._raises:
            raise self._raises
        return FakeAsyncResult(self.task_id)


class FakeTrackingSource:
    def __init__(self, tracking_key: str):
        self.__task_metadata_key__ = tracking_key
        self._last_enqueued_at = None

    def get_last_enqueued_at(self):
        return self._last_enqueued_at

    def set_last_enqueued_at(self, value):
        self._last_enqueued_at = value

    def backdate_last_enqueued_at(self, delta: timedelta) -> None:
        self._last_enqueued_at = (datetime.now(timezone.utc) - delta).isoformat()
