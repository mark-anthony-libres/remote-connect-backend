from contextlib import contextmanager
from contextvars import ContextVar
import os
import re
import uuid

from apps.app.utils.logger import Logger

_ANSI_ESCAPE_PATTERN = re.compile(r"\033\[[0-9;]*m")

_active_log_path: ContextVar[str | None] = ContextVar("analysis_run_log_path", default=None)


def analysis_logs_dir() -> str:
    return os.path.join(os.getcwd(), "logs", "analysis")


def analysis_log_filename(task_id) -> str:
    return f"{uuid.UUID(str(task_id)).hex}.log"


def analysis_log_path(task_id) -> str:
    return os.path.join(analysis_logs_dir(), analysis_log_filename(task_id))


def _write_line_to_analysis_log_file(line: str) -> None:
    log_path = _active_log_path.get()
    if not log_path:
        return

    plain_line = _ANSI_ESCAPE_PATTERN.sub("", line)
    try:
        with open(log_path, "a", encoding="utf-8") as log_file:
            log_file.write(plain_line + "\n")
    except OSError:
        pass


Logger.add_sink(_write_line_to_analysis_log_file)


@contextmanager
def analysis_run_context(task_id):
    os.makedirs(analysis_logs_dir(), exist_ok=True)
    token = _active_log_path.set(analysis_log_path(task_id))
    try:
        yield
    finally:
        _active_log_path.reset(token)
