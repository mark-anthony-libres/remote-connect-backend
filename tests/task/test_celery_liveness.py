from __future__ import annotations

from apps.app.modules.task.services.celery_liveness import (
    get_live_celery_task_ids,
    is_task_id_live,
)


class _FakeInspector:
    def __init__(self, active=None, reserved=None, raises: Exception | None = None):
        self._active = active
        self._reserved = reserved
        self._raises = raises

    def active(self):
        if self._raises:
            raise self._raises
        return self._active

    def reserved(self):
        if self._raises:
            raise self._raises
        return self._reserved


def _patch_inspect(monkeypatch, inspector: _FakeInspector) -> None:
    from apps.app.celery_app import celery_app

    monkeypatch.setattr(celery_app.control, "inspect", lambda timeout=None: inspector)


def test_combines_active_and_reserved_task_ids_across_multiple_workers(monkeypatch):
    inspector = _FakeInspector(
        active={
            "worker-1@host": [{"id": "task-a"}],
            "worker-2@host": [{"id": "task-b"}],
        },
        reserved={
            "worker-1@host": [{"id": "task-c"}],
            "worker-2@host": [],
        },
    )
    _patch_inspect(monkeypatch, inspector)

    assert get_live_celery_task_ids() == {"task-a", "task-b", "task-c"}


def test_returns_none_when_inspection_itself_fails(monkeypatch):
    inspector = _FakeInspector(raises=RuntimeError("no workers reachable"))
    _patch_inspect(monkeypatch, inspector)

    assert get_live_celery_task_ids() is None, (
        "an inspection failure must be distinguishable (None) from workers "
        "genuinely reporting nothing running (empty set)"
    )


def test_returns_empty_set_when_workers_answer_with_nothing_running(monkeypatch):
    inspector = _FakeInspector(active={}, reserved={})
    _patch_inspect(monkeypatch, inspector)

    assert get_live_celery_task_ids() == set()


def test_is_task_id_live_true_when_task_present(monkeypatch):
    inspector = _FakeInspector(active={"worker-1@host": [{"id": "task-a"}]}, reserved={})
    _patch_inspect(monkeypatch, inspector)

    assert is_task_id_live("task-a") is True
    assert is_task_id_live("task-missing") is False


def test_is_task_id_live_false_when_inspection_fails(monkeypatch):
    inspector = _FakeInspector(raises=RuntimeError("timeout"))
    _patch_inspect(monkeypatch, inspector)

    assert is_task_id_live("task-a") is False
