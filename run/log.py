"""
Manual log file cleanup script.

Usage:
  python -m run.log delete [-f]
"""

import argparse
import sys
from pathlib import Path

from apps.app.utils.logger import Logger


def logs_root() -> Path:
    return Path.cwd() / "logs"


def confirm_or_cancel(prompt: str, allowed_yes: set[str]) -> bool:
    return input(prompt).strip().lower() in allowed_yes


def cmd_delete(args: argparse.Namespace) -> None:
    log_files = sorted(logs_root().glob("api-centcom.*.log"))

    if not log_files:
        Logger.info("No log files found under logs/.")
        return

    if not args.force and not confirm_or_cancel(
        f"This will permanently delete {len(log_files)} log file(s) under logs/. Are you sure? (yes/no): ",
        {"yes", "y"},
    ):
        Logger.info("Operation cancelled.")
        return

    deleted_count = 0
    truncated_count = 0
    for log_file in log_files:
        try:
            log_file.unlink()
            deleted_count += 1
            continue
        except OSError:
            pass

        # Windows refuses to unlink a file that another process still has open,
        # but truncating its contents (same trick as logrotate's "copytruncate")
        # works even then, since the writer appends at its own file offset.
        try:
            with open(log_file, "w"):
                pass
            truncated_count += 1
        except OSError as exc:
            Logger.warning(f"Failed to clear {log_file.name}: {exc}")

    summary = f"Deleted {deleted_count}/{len(log_files)} log file(s) from logs/."
    if truncated_count:
        summary += f" Truncated {truncated_count} still in use by a running process."
    Logger.success(summary)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m run.log",
        description="Manage local api-centcom.*.log files under logs/.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_delete = subparsers.add_parser("delete", help="Delete all api-centcom.*.log files under logs/")
    p_delete.add_argument("-f", "--force", action="store_true", help="Skip confirmation prompt")
    p_delete.set_defaults(handler=cmd_delete)

    return parser


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help"}:
        build_parser().print_help()
        sys.exit(0 if len(sys.argv) >= 2 else 1)

    args = build_parser().parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
