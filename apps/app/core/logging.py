from __future__ import annotations

import logging
import logging.handlers
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from apps.app.core.settings import settings
from apps.app.utils.logger import Logger

_ANSI_ESCAPE_PATTERN = re.compile(r"\033\[[0-9;]*m")


class _PartRotatingFileHandler(logging.handlers.RotatingFileHandler):
    def __init__(
        self,
        *,
        logs_dir: Path,
        ts: str,
        max_bytes: int,
        backup_count: int,
        encoding: str = "utf-8",
    ) -> None:
        self._logs_dir = logs_dir
        self._ts = ts
        self._part_index = 0
        filename = self._build_filename(self._part_index)
        super().__init__(
            filename=str(filename),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding=encoding,
            delay=True,
        )

    def _build_filename(self, part_index: int) -> Path:
        return self._logs_dir / f"api-centcom.{self._ts}.part-{part_index}.log"

    def doRollover(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None

        self._part_index += 1
        self.baseFilename = os.fspath(self._build_filename(self._part_index))
        self.mode = "a"
        if not self.delay:
            self.stream = self._open()


def _build_file_handler(logs_dir: Optional[str] = None) -> _PartRotatingFileHandler:
    base_dir = Path(logs_dir) if logs_dir else Path.cwd() / "logs"
    base_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    file_handler = _PartRotatingFileHandler(
        logs_dir=base_dir,
        ts=ts,
        max_bytes=50 * 1024 * 1024,
        backup_count=1000,
    )

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    file_handler.setFormatter(formatter)

    return file_handler


def setup_logging(*, logs_dir: Optional[str] = None) -> None:
    level = getattr(logging, (settings.log_level or "INFO").upper(), logging.INFO)

    file_handler = _build_file_handler(logs_dir)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(file_handler.formatter)

    logging.basicConfig(level=level, handlers=[stream_handler, file_handler])

    for logger_name in ("uvicorn", "uvicorn.access"):
        target_logger = logging.getLogger(logger_name)
        target_logger.addHandler(file_handler)
        target_logger.propagate = False

    console_mirror_logger = logging.getLogger("app.console")
    console_mirror_logger.setLevel(level)
    console_mirror_logger.propagate = False
    console_mirror_logger.addHandler(file_handler)

    Logger.add_sink(lambda line: console_mirror_logger.info(_ANSI_ESCAPE_PATTERN.sub("", line)))


_worker_logging_state: dict = {"pid": None, "sink": None}


def setup_worker_logging(*, logs_dir: Optional[str] = None) -> None:
    current_pid = os.getpid()

    if _worker_logging_state["pid"] == current_pid:
        return

    if _worker_logging_state["sink"] is not None:
        Logger.remove_sink(_worker_logging_state["sink"])

    level = getattr(logging, (settings.log_level or "INFO").upper(), logging.INFO)

    file_handler = _build_file_handler(logs_dir)

    console_mirror_logger = logging.getLogger("app.console")
    console_mirror_logger.setLevel(level)
    console_mirror_logger.propagate = False
    console_mirror_logger.handlers = [file_handler]

    sink = lambda line: console_mirror_logger.info(_ANSI_ESCAPE_PATTERN.sub("", line))
    Logger.add_sink(sink)

    _worker_logging_state["pid"] = current_pid
    _worker_logging_state["sink"] = sink
