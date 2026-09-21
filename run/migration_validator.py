import glob
import os
import re
import subprocess
import sys
import time
import uuid

import psycopg2
from psycopg2 import sql

from apps.app.core.settings import settings

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass

DEFAULT_DATABASE_NAME = "central-command-migration-testing"
SEPARATOR = "=" * 50
MIGRATIONS_DIR = os.path.join("database", "migrations")
RUNNING_STEP_PATTERN = re.compile(
    r"Running (upgrade|downgrade) (\S+) -> (\S+)(?:, (\S.*))?"
)


def find_alembic_exe():
    alembic_exe = os.path.join(os.path.dirname(sys.executable), "alembic.exe")
    if not os.path.exists(alembic_exe):
        alembic_exe = "alembic"
    return alembic_exe


def _migration_file_for_revision(revision_id: str) -> str | None:
    matches = glob.glob(os.path.join(MIGRATIONS_DIR, f"{revision_id}_*.py"))
    return matches[0] if matches else None


def find_failing_migration(log_output: str) -> str | None:
    steps = RUNNING_STEP_PATTERN.findall(log_output)
    if not steps:
        return None

    direction, from_rev, to_rev, _message = steps[-1]
    executing_revision = from_rev if direction == "downgrade" else to_rev

    migration_file = _migration_file_for_revision(executing_revision)
    location = migration_file or "unknown file"
    return f"{location} (revision {executing_revision}, {direction})"


class MigrationValidator:
    def __init__(self, base_database_name: str = DEFAULT_DATABASE_NAME):
        self.base_database_name = base_database_name
        self.database_name = f"{base_database_name}_{uuid.uuid4().hex[:8]}"
        self.alembic_exe = find_alembic_exe()
        self.duration = 0.0
        self.failed_migration: str | None = None

    def _connect(self):
        conn = psycopg2.connect(
            host=settings.pg_db_host,
            port=settings.pg_db_port,
            dbname=settings.pg_db_name,
            user=settings.pg_db_user,
            password=settings.pg_db_password,
        )
        conn.autocommit = True
        return conn

    def has_create_database_permission(self) -> bool:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT rolcreatedb FROM pg_roles WHERE rolname = current_user")
                row = cur.fetchone()
                return bool(row and row[0])
        finally:
            conn.close()

    def _check_permission_safe(self) -> bool:
        try:
            return self.has_create_database_permission()
        except Exception:
            return False

    def create_database(self) -> None:
        self.drop_database()
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(self.database_name)))
        finally:
            conn.close()

    def drop_database(self) -> None:
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    (self.database_name,),
                )
                cur.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(self.database_name)))
        finally:
            conn.close()

    def _run_alembic(self, *args: str) -> bool:
        cmd = [
            self.alembic_exe, "-c", "infra/alembic.ini",
            "-x", f"database={self.database_name}",
            *args,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        output = result.stdout + result.stderr
        print(output, end="" if output.endswith("\n") else "\n")

        if result.returncode != 0:
            self.failed_migration = find_failing_migration(output)

        return result.returncode == 0

    def validate(self, target: str) -> bool:
        started_at = time.monotonic()
        success = False
        database_created = False

        print(SEPARATOR)
        print("Migration Validation")
        print(SEPARATOR)
        print()

        print("Reading database configuration...")
        print(f"✓ Configuration loaded ({settings.pg_db_name}@{settings.pg_db_host}:{settings.pg_db_port}).")
        print()

        print("Checking CREATE DATABASE permission...")
        if not self._check_permission_safe():
            print("✗ Permission denied.")
            print()
            print("The current database user does not have CREATE DATABASE permission.")
            print()
            print("Migration validation cannot continue.")
            print()
            print("The real database was NOT modified.")
            self.duration = time.monotonic() - started_at
            return False
        print("✓ Permission granted.")
        print()

        try:
            print("Creating temporary validation database...")
            print(f"Database: {self.database_name}")
            self.create_database()
            database_created = True
            print("✓ Database created.")
            print()

            print("Switching migration context...")
            print("✓ Validation database activated.")
            print()

            print("Running migration upgrade...")
            print(f"alembic upgrade {target} (validation database)")
            print()
            if not self._run_alembic("upgrade", target):
                print("✗ Upgrade validation failed.")
                if self.failed_migration:
                    print(f"Failed in: {self.failed_migration}")
            else:
                print("✓ Upgrade validation succeeded.")
                print()

                print("Running migration downgrade...")
                print("alembic downgrade base (validation database)")
                print()
                if not self._run_alembic("downgrade", "base"):
                    print("✗ Downgrade validation failed.")
                    if self.failed_migration:
                        print(f"Failed in: {self.failed_migration}")
                else:
                    print("✓ Downgrade validation succeeded.")
                    success = True
        finally:
            print()
            print("Cleaning up validation database...")
            if database_created:
                try:
                    self.drop_database()
                    print("✓ Database dropped.")
                except Exception:
                    print()
                    print("⚠ Warning")
                    print()
                    print("Failed to remove temporary database:")
                    print()
                    print(self.database_name)
                    print()
                    print("Please remove it manually before running migrations again.")
                    success = False
            print()

        self.duration = time.monotonic() - started_at

        if success:
            print("Validation completed successfully.")
        else:
            print("Migration validation failed.")
            print()
            print("The real database was NOT modified.")

        return success
