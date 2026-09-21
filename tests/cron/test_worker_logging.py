from __future__ import annotations

import os

from apps.app.core import logging as app_logging
from apps.app.utils.logger import Logger


def test_setup_worker_logging_is_idempotent_within_the_same_process(tmp_path):
    before = len(Logger._sinks)

    app_logging.setup_worker_logging(logs_dir=str(tmp_path))
    after_first = len(Logger._sinks)

    app_logging.setup_worker_logging(logs_dir=str(tmp_path))
    after_second = len(Logger._sinks)

    assert after_first == before + 1, "first call in a process should register exactly one sink"
    assert after_second == after_first, "a repeat call from the same pid must be a no-op"


def test_setup_worker_logging_reconfigures_across_a_simulated_fork(tmp_path, monkeypatch):
    app_logging.setup_worker_logging(logs_dir=str(tmp_path))
    after_parent = len(Logger._sinks)
    parent_pid = app_logging._worker_logging_state["pid"]

    fake_child_pid = parent_pid + 999999
    monkeypatch.setattr(os, "getpid", lambda: fake_child_pid)

    app_logging.setup_worker_logging(logs_dir=str(tmp_path))

    assert len(Logger._sinks) == after_parent, (
        "a forked child (different pid) must swap its inherited sink for a fresh one, "
        "not accumulate a second sink"
    )
    assert app_logging._worker_logging_state["pid"] == fake_child_pid
