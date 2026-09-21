import sys
import argparse
import datetime
import importlib.util
import os
import subprocess
import tempfile
import time
import glob
import webbrowser
from zoneinfo import ZoneInfo

from run.migration_validator import SEPARATOR
from run.migration_test import MigrationGraph, MigrationStrictValidator
from run.migration_graph import render_html

PH_TZ = ZoneInfo("Asia/Manila")

def find_alembic_exe():
    alembic_exe = os.path.join(os.path.dirname(sys.executable), 'alembic.exe')
    if not os.path.exists(alembic_exe):
        alembic_exe = 'alembic'
    return alembic_exe


def _next_rev_id():
    return datetime.datetime.now(PH_TZ).strftime("%Y%m%d_%H_%S")


def _format_with_black(migrations_dir):
    venv_python = os.path.join(os.path.dirname(sys.executable), 'python.exe')
    result = subprocess.run(
        [venv_python, '-m', 'black', migrations_dir],
        capture_output=True,
        text=True
    )
    if result.returncode != 0:
        print(f"\n⚠️  black formatting failed:\n{result.stderr}")

def create_migration(message, autogenerate=False):
    alembic_exe = find_alembic_exe()
    migrations_dir = os.path.join("database", "migrations")
    if not os.path.exists(migrations_dir):
        os.makedirs(migrations_dir)
    rev_id = _next_rev_id()
    cmd = [
        alembic_exe, "-c", "infra/alembic.ini", "revision",
        "-m", message, "--rev-id", rev_id
    ]
    if autogenerate:
        cmd.append("--autogenerate")
    result = subprocess.run(cmd)
    if result.returncode == 0:
        _format_with_black(migrations_dir)
    sys.exit(result.returncode)

def update_current_migration(message, force=False):
    migrations_dir = os.path.join("database", "migrations")
    migration_files = sorted(
        glob.glob(os.path.join(migrations_dir, "[0-9][0-9][0-9]_*.py")),
        reverse=True
    )
    if not migration_files:
        print("No migration file to update. Use 'create' to make the first migration.")
        sys.exit(1)
    latest_file = migration_files[0]
    filename = os.path.basename(latest_file)
    rev_id = filename.split('_')[0]
    alembic_exe = find_alembic_exe()
    if force:
        stamp_cmd = [
            alembic_exe, "-c", "infra/alembic.ini", "stamp", "head"
        ]
        stamp_result = subprocess.run(stamp_cmd)
        if stamp_result.returncode != 0:
            print("Failed to stamp database to head. Aborting.")
            sys.exit(stamp_result.returncode)
    cmd = [
        alembic_exe, "-c", "infra/alembic.ini", "revision",
        "--autogenerate", "-m", message, "--rev-id", rev_id
    ]
    result = subprocess.run(cmd)
    if result.returncode == 0:
        _format_with_black(migrations_dir)
    sys.exit(result.returncode)

def merge_heads(message):
    alembic_exe = find_alembic_exe()
    migrations_dir = os.path.join("database", "migrations")
    rev_id = _next_rev_id()
    cmd = [
        alembic_exe, "-c", "infra/alembic.ini", "merge",
        "heads", "-m", message, "--rev-id", rev_id
    ]
    result = subprocess.run(cmd)
    if result.returncode == 0:
        _format_with_black(migrations_dir)
        print(f"\n✅ Merged heads into new revision '{rev_id}'.")
    else:
        print(f"\n❌ Merge failed with exit code {result.returncode}.")
    sys.exit(result.returncode)

def _run_real_upgrade(target, sql=False):
    alembic_exe = find_alembic_exe()
    cmd = [
        alembic_exe, "-c", "infra/alembic.ini", "upgrade", target
    ]
    if sql:
        cmd.append("--sql")
    result = subprocess.run(cmd)
    if result.returncode == 0:
        if not sql:
            print(f"\n✅ Migration upgrade to '{target}' completed successfully.")
    else:
        print(f"\n❌ Migration upgrade to '{target}' failed with exit code {result.returncode}.")
    return result.returncode


def upgrade_db(target, sql=False, force=False):
    if sql:
        sys.exit(_run_real_upgrade(target, sql=True))

    if force:
        print(SEPARATOR)
        print("Force Mode")
        print(SEPARATOR)
        print()
        print("Validation skipped (--force).")
        print()
        print("Running migration directly against the real database...")
        print()
        sys.exit(_run_real_upgrade(target))

    validator = MigrationStrictValidator()
    if target == "head":
        validation_passed = validator.validate(only_new=True)
    else:
        validation_passed = validator.validate_against_revision(target)
    print()

    if not validation_passed:
        sys.exit(1)

    print(SEPARATOR)
    print("Executing Real Migration")
    print(SEPARATOR)
    print()
    print("Restoring original configuration...")
    print("✓ Configuration restored.")
    print()
    print("Running migration...")
    print(f"python -m run.migration upgrade {target}")
    print()

    migration_started_at = time.monotonic()
    exit_code = _run_real_upgrade(target)
    migration_duration = time.monotonic() - migration_started_at

    print()
    print(SEPARATOR)
    print("Completed" if exit_code == 0 else "Failed")
    print(SEPARATOR)
    print()
    print(f"Validation Time: {validator.duration:.2f} seconds")
    print(f"Migration Time: {migration_duration:.2f} seconds")

    sys.exit(exit_code)

def test_migrations(target=None):
    validator = MigrationStrictValidator()
    if target == "head":
        validation_passed = validator.validate(only_new=True)
    elif target:
        validation_passed = validator.validate_against_revision(target)
    else:
        validation_passed = validator.validate()
    print()
    print(f"Validation Time: {validator.duration:.2f} seconds")
    sys.exit(0 if validation_passed else 1)

def downgrade_db(target, sql=False):
    alembic_exe = find_alembic_exe()
    cmd = [
        alembic_exe, "-c", "infra/alembic.ini", "downgrade", target
    ]
    if sql:
        cmd.append("--sql")
    result = subprocess.run(cmd)
    if result.returncode == 0:
        if not sql:
            print(f"\n✅ Migration downgrade to '{target}' completed successfully.")
    else:
        print(f"\n❌ Migration downgrade to '{target}' failed with exit code {result.returncode}.")
    sys.exit(result.returncode)

def show_current():
    alembic_exe = find_alembic_exe()
    cmd = [
        alembic_exe, "-c", "infra/alembic.ini", "current"
    ]
    result = subprocess.run(cmd)
    sys.exit(result.returncode)

def show_heads(verbose=False):
    alembic_exe = find_alembic_exe()
    cmd = [
        alembic_exe, "-c", "infra/alembic.ini", "heads"
    ]
    if verbose:
        cmd.append("--verbose")
    result = subprocess.run(cmd)
    sys.exit(result.returncode)

def show_graph(output=None, no_open=False):
    revisions = MigrationGraph().get_revisions()
    if not revisions:
        print("No migrations found.")
        sys.exit(1)

    project_name = os.path.basename(os.getcwd())
    html = render_html(revisions, project_name)

    output_path = os.path.abspath(output or os.path.join(tempfile.gettempdir(), "migration_graph.html"))
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    heads = [r.revision for r in revisions if r.is_head]
    print(f"Wrote graph for {len(revisions)} revisions ({len(heads)} head(s)) to:")
    print(f"  {output_path}")

    if not no_open:
        webbrowser.open(f"file://{output_path.replace(os.sep, '/')}")

    sys.exit(0)

def stamp_db(target):
    alembic_exe = find_alembic_exe()
    cmd = [
        alembic_exe, "-c", "infra/alembic.ini", "stamp", target
    ]
    result = subprocess.run(cmd)
    if result.returncode == 0:
        print(f"\n✅ Database stamped to '{target}'.")
    else:
        print(f"\n❌ Stamp to '{target}' failed with exit code {result.returncode}.")
    sys.exit(result.returncode)

def _resolve_migration_path(target):
    if os.path.isfile(target):
        return target

    matches = glob.glob(os.path.join("database", "migrations", f"{target}_*.py"))
    if not matches:
        print(f"No migration file found for '{target}' (looked for a file path, "
              f"or a revision id under database/migrations/).")
        sys.exit(1)
    if len(matches) > 1:
        print(f"'{target}' matches more than one migration file:")
        for match in matches:
            print(f"  {match}")
        sys.exit(1)
    return matches[0]

def apply_migration_file(target, downgrade=False):
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    from database.session_factory import get_engine

    path = _resolve_migration_path(target)
    direction = "downgrade" if downgrade else "upgrade"

    print(SEPARATOR)
    print(f"Applying '{path}' directly ({direction}()) - the migrations table will NOT be updated.")
    print(SEPARATOR)
    print()

    spec = importlib.util.spec_from_file_location("_applied_migration_file", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    fn = getattr(migration, direction, None)
    if fn is None:
        print(f"\n❌ '{path}' has no {direction}() function.")
        sys.exit(1)

    engine = get_engine()
    try:
        with engine.begin() as connection:
            ctx = MigrationContext.configure(connection)
            with Operations.context(ctx):
                fn()
    except Exception as e:
        print(f"\n❌ {direction}() failed and was rolled back: {e}")
        sys.exit(1)

    print(f"\n✅ {direction}() applied successfully from '{path}'.")
    sys.exit(0)

def build_parser():
    parser = argparse.ArgumentParser(prog="python -m run.migration")
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_p = subparsers.add_parser("create", help="Create a new migration")
    create_p.add_argument("message")
    create_p.add_argument(
        "--autogenerate", "-g", action="store_true",
        help="Autodetect model/DB drift and populate the migration. Without this, upgrade()/downgrade() are left blank for you to write by hand."
    )

    update_p = subparsers.add_parser("update", help="Regenerate the latest migration file in place")
    update_p.add_argument("subcommand", choices=["current"])
    update_p.add_argument("message", nargs="?", default="update migration")
    update_p.add_argument("--force", action="store_true", help="Stamp the database to head before regenerating")

    upgrade_p = subparsers.add_parser("upgrade", help="Upgrade the database to a target revision")
    upgrade_p.add_argument("target")
    upgrade_p.add_argument("--sql", action="store_true", help="Print the SQL without executing it")
    upgrade_p.add_argument(
        "--force", "-f", action="store_true",
        help="Skip temporary-schema validation and upgrade the real database directly"
    )

    test_p = subparsers.add_parser("test", help="Validate migration upgrade()/downgrade() reversibility")
    test_p.add_argument(
        "target", nargs="?", default=None,
        help="'head': clone the current database's schema and validate only the migrations added since its current revision. A specific revision id: validate the range between the current database revision and that revision. Omit to validate the full Base -> Head history from scratch.",
    )

    downgrade_p = subparsers.add_parser("downgrade", help="Downgrade the database to a target revision")
    downgrade_p.add_argument("target")
    downgrade_p.add_argument("--sql", action="store_true", help="Print the SQL without executing it")

    subparsers.add_parser("current", help="Show the current database revision")

    merge_p = subparsers.add_parser("merge", help="Merge multiple heads into a single new head")
    merge_p.add_argument("message", nargs="?", default="merge heads")

    heads_p = subparsers.add_parser("heads", help="Show current head revision(s)")
    heads_p.add_argument("--verbose", "-v", action="store_true")

    stamp_p = subparsers.add_parser("stamp", help="Stamp the database to a revision without running migrations")
    stamp_p.add_argument("target")

    apply_p = subparsers.add_parser(
        "apply",
        help="Run one migration file's upgrade()/downgrade() directly, without recording it in the migrations table",
    )
    apply_p.add_argument("target", help="A migration file path, or its revision id (e.g. 20260830_09_00)")
    apply_p.add_argument("--downgrade", action="store_true", help="Run downgrade() instead of upgrade()")

    graph_p = subparsers.add_parser("graph", help="Render the migration dependency graph as a local HTML page")
    graph_p.add_argument("--output", "-o", default=None, help="Path to write the HTML file (default: a temp file, overwritten each run)")
    graph_p.add_argument("--no-open", action="store_true", help="Write the file without opening it in a browser")

    return parser

def main():
    args = build_parser().parse_args()

    if args.command == "create":
        create_migration(args.message, autogenerate=args.autogenerate)
    elif args.command == "update":
        update_current_migration(args.message, force=args.force)
    elif args.command == "upgrade":
        upgrade_db(args.target, sql=args.sql, force=args.force)
    elif args.command == "test":
        test_migrations(target=args.target)
    elif args.command == "downgrade":
        downgrade_db(args.target, sql=args.sql)
    elif args.command == "current":
        show_current()
    elif args.command == "merge":
        merge_heads(args.message)
    elif args.command == "heads":
        show_heads(verbose=args.verbose)
    elif args.command == "stamp":
        stamp_db(args.target)
    elif args.command == "apply":
        apply_migration_file(args.target, downgrade=args.downgrade)
    elif args.command == "graph":
        show_graph(output=args.output, no_open=args.no_open)

if __name__ == "__main__":
    main()
