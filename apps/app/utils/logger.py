from datetime import datetime
import sys
import traceback
from typing import Callable, List
from zoneinfo import ZoneInfo

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


class Logger:

    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    RESET = "\033[0m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"

    BOLD = "\033[1m"

    WIDTH = 80

    _sinks: List[Callable[[str], None]] = []

    @staticmethod
    def add_sink(sink: Callable[[str], None]) -> None:
        Logger._sinks.append(sink)

    @staticmethod
    def remove_sink(sink: Callable[[str], None]) -> None:
        if sink in Logger._sinks:
            Logger._sinks.remove(sink)

    @staticmethod
    def _get_timestamp() -> str:
        tz = ZoneInfo("Asia/Singapore")
        now = datetime.now(tz)

        tz_offset = now.strftime("%z")[:3]
        ms = now.strftime("%f")[:3]

        return now.strftime(f"%a, %b %d, %Y at %I:%M:%S.{ms} %p GMT{tz_offset}")

    @staticmethod
    def _notify_sinks(line: str) -> None:
        for sink in Logger._sinks:
            sink(line)

    @staticmethod
    def _emit(line: str) -> None:
        print(line)
        Logger._notify_sinks(line)

    @staticmethod
    def success(message: str):
        Logger._emit(f"[{Logger._get_timestamp()}] {Logger.GREEN}{message}{Logger.RESET}")

    @staticmethod
    def warning(message: str):
        Logger._emit(f"[{Logger._get_timestamp()}] {Logger.YELLOW}{message}{Logger.RESET}")

    @staticmethod
    def error(message: str):
        Logger._emit(f"[{Logger._get_timestamp()}] {Logger.RED}{message}{Logger.RESET}")

    @staticmethod
    def info(message: str):
        Logger._emit(f"[{Logger._get_timestamp()}] {Logger.BLUE}{message}{Logger.RESET}")

    @staticmethod
    def section(message: str):
        border = "═" * Logger.WIDTH

        title = f"  {message}  "

        centered = title.center(Logger.WIDTH, "═")

        Logger._emit("")
        Logger._emit(f"{Logger.CYAN}{Logger.BOLD}{border}{Logger.RESET}")
        Logger._emit(f"{Logger.CYAN}{Logger.BOLD}{centered}{Logger.RESET}")
        Logger._emit(f"{Logger.CYAN}{Logger.BOLD}{border}{Logger.RESET}")
        Logger._emit("")

    @staticmethod
    def debug(message: str):
        Logger._emit(f"[{Logger._get_timestamp()}] {Logger.MAGENTA}[DEBUG] {message}{Logger.RESET}")

    @staticmethod
    def exception(message: str):
        Logger._emit(f"{Logger.RED}{message}{Logger.RESET}")
        traceback.print_exc()
        Logger._notify_sinks(traceback.format_exc().rstrip("\n"))
