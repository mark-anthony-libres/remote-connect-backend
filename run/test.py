import argparse
import subprocess
import sys

SERVICES = {
    "cron": "tests/cron",
    "scheduler": "tests/cron",
    "sync": "tests/sync",
    # "ticketing": "tests/ticketing",
}

ALL_TESTS_PATH = "tests"

ALL_TESTS_IGNORE = ["tests/impersonation"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m run.test")
    parser.add_argument(
        "service",
        choices=[*sorted(SERVICES.keys()), "all"],
        help="Which service's tests to run, or 'all' to run the full suite.",
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Extra arguments passed through to pytest (e.g. -k, -s, -x).",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    if args.service == "all":
        ignore_args = [f"--ignore={path}" for path in ALL_TESTS_IGNORE]
        cmd = [sys.executable, "-m", "pytest", ALL_TESTS_PATH, *ignore_args, "-v", *args.pytest_args]
    else:
        cmd = [sys.executable, "-m", "pytest", SERVICES[args.service], "-v", *args.pytest_args]

    result = subprocess.run(cmd)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
