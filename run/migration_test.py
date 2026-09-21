from __future__ import annotations

import difflib
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass

import psycopg2
from alembic.config import Config
from alembic.script import ScriptDirectory

from apps.app.core.settings import settings
from run.migration_validator import MigrationValidator, SEPARATOR


def _find_pg_dump() -> str:
    if settings.pg_dump_path:
        if not os.path.exists(settings.pg_dump_path):
            raise RuntimeError(
                f"PG_DUMP_PATH is set to '{settings.pg_dump_path}', but no file exists there. "
                "Fix PG_DUMP_PATH in .env, or clear it to rely on PATH instead."
            )
        return settings.pg_dump_path

    found = shutil.which("pg_dump")
    if found:
        return found

    raise RuntimeError(
        "pg_dump was not found. Either add it to PATH, or set PG_DUMP_PATH in .env "
        "to its full path (see .env.example)."
    )


@dataclass(frozen=True)
class Revision:
    revision: str
    down_revision: tuple[str, ...]
    doc: str
    path: str
    is_head: bool
    is_branch_point: bool
    is_merge_point: bool


@dataclass(frozen=True)
class RevisionResult:
    revision: str
    doc: str
    passed: bool


class MigrationGraph:
    def __init__(self, config_path: str = "infra/alembic.ini"):
        self.config = Config(config_path)
        self.script = ScriptDirectory.from_config(self.config)

    def get_revisions(self) -> list[Revision]:
        revisions = [self._to_revision(rev) for rev in self.script.walk_revisions()]

        revisions.reverse()

        return revisions

    @staticmethod
    def _to_revision(rev) -> Revision:
        down_revision = rev.down_revision

        if down_revision is None:
            down_revision = ()
        elif isinstance(down_revision, str):
            down_revision = (down_revision,)
        else:
            down_revision = tuple(down_revision)

        return Revision(
            revision=rev.revision,
            down_revision=down_revision,
            doc=rev.doc,
            path=rev.path,
            is_head=rev.is_head,
            is_branch_point=rev.is_branch_point,
            is_merge_point=rev.is_merge_point,
        )


class DatabaseState:
    def __init__(self, dump_text: str):
        self.dump_text = dump_text

    def __eq__(self, other) -> bool:
        if not isinstance(other, DatabaseState):
            return NotImplemented
        return self.dump_text == other.dump_text

    def diff(self, other: "DatabaseState") -> list[str]:
        return list(
            difflib.unified_diff(
                self.dump_text.splitlines(),
                other.dump_text.splitlines(),
                fromfile="before",
                tofile="after",
                lineterm="",
            )
        )


class DatabaseStateInspector:
    def __init__(self, database_name: str, version_table: str):
        self.database_name = database_name
        self.version_table = version_table
        self.pg_dump_exe = _find_pg_dump()

    def capture(self) -> DatabaseState:
        cmd = [
            self.pg_dump_exe,
            "--schema-only",
            "--no-owner",
            "--no-privileges",
            "--no-tablespaces",
            f"--exclude-table={self.version_table}",
            "-h", settings.pg_db_host,
            "-p", str(settings.pg_db_port),
            "-U", settings.pg_db_user,
            self.database_name,
        ]

        env = {**os.environ, "PGPASSWORD": settings.pg_db_password}
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)

        if result.returncode != 0:
            raise RuntimeError(
                f"pg_dump failed for database '{self.database_name}':\n{result.stderr}"
            )

        dump_text = self._normalize(result.stdout)
        dump_text = self._sort_table_columns(dump_text)
        return DatabaseState(dump_text)

    @staticmethod
    def _normalize(dump_text: str) -> str:
        noise_prefixes = ("-- Dumped ", "-- Started ", "\\restrict ", "\\unrestrict ")
        lines = [
            line.rstrip()
            for line in dump_text.splitlines()
            if line.strip() and not line.startswith(noise_prefixes)
        ]
        return "\n".join(lines)

    _CREATE_TABLE_RE = re.compile(r"(CREATE TABLE [^\n]+\()\n(.*?)\n(\);)", re.DOTALL)

    @classmethod
    def _sort_table_columns(cls, dump_text: str) -> str:
        def sort_block(match: re.Match) -> str:
            header, body, footer = match.group(1), match.group(2), match.group(3)

            lines = [line.rstrip(",") for line in body.split("\n")]
            lines.sort(key=lambda line: line.strip().split()[0] if line.strip() else "")

            return f"{header}\n" + ",\n".join(lines) + f"\n{footer}"

        return cls._CREATE_TABLE_RE.sub(sort_block, dump_text)


class _ValidationFailure(Exception):
    def __init__(self, revision_id: str):
        super().__init__(revision_id)
        self.revision_id = revision_id


class MigrationStrictValidator:
    def __init__(
        self,
        config_path: str = "infra/alembic.ini",
        base_database_name: str = "central-command-migration-strict-testing",
    ):
        self.config_path = config_path
        self.graph = MigrationGraph(config_path)
        self.sandbox_db = MigrationValidator(base_database_name=base_database_name)
        self.alembic_exe = self.sandbox_db.alembic_exe
        self.version_table = self.graph.config.get_main_option("version_table") or "alembic_version"
        self.state_inspector = DatabaseStateInspector(self.sandbox_db.database_name, self.version_table)

        self.duration = 0.0
        self.results: list[RevisionResult] = []
        self.failed_revision: str | None = None

    def _run_alembic(self, *args: str) -> tuple[bool, str]:
        cmd = [
            self.alembic_exe, "-c", self.config_path,
            "-x", f"database={self.sandbox_db.database_name}",
            *args,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode == 0, result.stdout + result.stderr

    def _run_alembic_or_fail(self, action: str, target: str, revision_id: str, failure_message: str) -> None:
        succeeded, output = self._run_alembic(action, target)
        if not succeeded:
            print(f"✗ {failure_message}")
            print(output)
            raise _ValidationFailure(revision_id)

    def _group_children_by_parent_revision(self, revisions: list[Revision]) -> dict:
        children_by_parent = {}
        for rev in revisions:
            for parent_id in rev.down_revision:
                children_by_parent.setdefault(parent_id, []).append(rev)
        return children_by_parent

    def _find_revisions_pending_merge(self, revisions: list[Revision]) -> set:
        children_by_parent = self._group_children_by_parent_revision(revisions)
        pending_merge = set()

        for rev in revisions:
            if not rev.is_branch_point:
                continue

            for child in children_by_parent.get(rev.revision, []):
                node = child

                while True:
                    pending_merge.add(node.revision)

                    if node.is_merge_point:
                        break

                    next_nodes = children_by_parent.get(node.revision, [])
                    if len(next_nodes) != 1:
                        break

                    node = next_nodes[0]

        return pending_merge

    def _ancestor_closure(self, revisions: list[Revision], heads: set) -> set:
        revisions_by_id = {r.revision: r for r in revisions}
        closure = set()
        stack = list(heads)

        while stack:
            revision_id = stack.pop()
            if revision_id in closure:
                continue
            closure.add(revision_id)

            rev = revisions_by_id.get(revision_id)
            if rev:
                stack.extend(rev.down_revision)

        return closure

    def _frontier_of(self, revisions: list[Revision], subset: set) -> set:
        children_by_parent = self._group_children_by_parent_revision(revisions)
        return {
            revision_id for revision_id in subset
            if not any(child.revision in subset for child in children_by_parent.get(revision_id, []))
        }

    def _connect_to_database(self, database_name: str):
        return psycopg2.connect(
            host=settings.pg_db_host,
            port=settings.pg_db_port,
            dbname=database_name,
            user=settings.pg_db_user,
            password=settings.pg_db_password,
        )

    def _get_real_database_applied_revisions(self) -> set:
        connection = self._connect_to_database(settings.pg_db_name)
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT version_num FROM {self.version_table}")
                rows = cursor.fetchall()
        finally:
            connection.close()

        if not rows:
            raise RuntimeError(
                f"No rows found in '{self.version_table}' on database "
                f"'{settings.pg_db_name}' -- has it ever been migrated? "
                "'test head' requires an already-migrated database."
            )

        return {row[0] for row in rows}

    def _dump_real_database_schema(self) -> str:
        cmd = [
            self.state_inspector.pg_dump_exe,
            "--schema-only",
            "--no-owner",
            "--no-privileges",
            "--no-tablespaces",
            "-h", settings.pg_db_host,
            "-p", str(settings.pg_db_port),
            "-U", settings.pg_db_user,
            settings.pg_db_name,
        ]

        env = {**os.environ, "PGPASSWORD": settings.pg_db_password}
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)

        if result.returncode != 0:
            raise RuntimeError(
                f"pg_dump failed for database '{settings.pg_db_name}':\n{result.stderr}"
            )

        return "\n".join(
            line for line in result.stdout.splitlines()
            if not line.startswith("\\restrict ") and not line.startswith("\\unrestrict ")
        )

    def _seed_sandbox_from_real_database(self, real_database_heads: set) -> None:
        self._clone_real_database_schema_into_sandbox()
        self._set_sandbox_current_revision(real_database_heads)

    def _clone_real_database_schema_into_sandbox(self) -> None:
        print("Cloning current database schema into validation database...")
        schema_sql = self._dump_real_database_schema()

        connection = self._connect_to_database(self.sandbox_db.database_name)
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                cursor.execute(schema_sql)
        finally:
            connection.close()
        print("✓ Schema cloned.")

    def _set_sandbox_current_revision(self, revision_ids: set) -> None:
        print(f"Setting validation database's current revision to: {', '.join(sorted(revision_ids))}")
        connection = self._connect_to_database(self.sandbox_db.database_name)
        connection.autocommit = True
        try:
            with connection.cursor() as cursor:
                for revision_id in revision_ids:
                    cursor.execute(
                        f"INSERT INTO {self.version_table} (version_num) VALUES (%s)",
                        (revision_id,),
                    )
        finally:
            connection.close()
        print("✓ Current revision set.")
        print()

    def _downgrade_sandbox_to_frontier(self, frontier: set) -> None:
        first, *remaining = sorted(frontier)

        self._run_alembic_or_fail(
            "downgrade", first, first,
            f"Failed downgrading validation database to '{first}'",
        )
        self._upgrade_to_required_parents(set(remaining), set(), first)

    def _upgrade_to_required_parents(self, required_parents: set, current_heads: set, revision_id: str) -> None:
        for parent_id in sorted(required_parents - current_heads):
            self._run_alembic_or_fail(
                "upgrade", parent_id, revision_id,
                f"Failed preparing parent state '{parent_id}' for revision {revision_id}",
            )

    def _check_reversibility(self, rev: Revision) -> tuple[DatabaseState, DatabaseState]:
        state_before = self.state_inspector.capture()

        self._run_alembic_or_fail(
            "upgrade", rev.revision, rev.revision,
            f"Upgrade failed for revision {rev.revision}",
        )

        downgrade_target = sorted(rev.down_revision)[0] if rev.down_revision else "base"
        self._run_alembic_or_fail(
            "downgrade", downgrade_target, rev.revision,
            f"Downgrade failed for revision {rev.revision}",
        )

        state_after = self.state_inspector.capture()
        return state_before, state_after

    def _report_mismatch(self, rev: Revision, before: DatabaseState, after: DatabaseState) -> None:
        print(f"✗ Database state mismatch for revision {rev.revision} ({rev.doc})")
        print("upgrade() and downgrade() are not structural inverses.")
        print()
        print("Diff (database state before upgrade -> state after upgrade+downgrade):")
        for line in before.diff(after):
            print(line)

    def _validate_revision(self, rev: Revision, current_heads: set, revisions_pending_merge: set) -> set:
        required_parents = set(rev.down_revision)
        self._upgrade_to_required_parents(required_parents, current_heads, rev.revision)

        state_before, state_after = self._check_reversibility(rev)
        is_match = state_before == state_after

        self.results.append(RevisionResult(rev.revision, rev.doc, is_match))

        if not is_match:
            self._report_mismatch(rev, state_before, state_after)
            raise _ValidationFailure(rev.revision)

        print(f"✓ {rev.revision} ({rev.doc or 'no message'})")

        if rev.revision in revisions_pending_merge:
            return required_parents

        self._run_alembic_or_fail(
            "upgrade", rev.revision, rev.revision,
            f"Failed to permanently apply revision {rev.revision}",
        )
        return {rev.revision}

    def _validate_all_revisions(
        self,
        revisions: list[Revision],
        revisions_pending_merge: set,
        initial_heads: set = frozenset(),
    ) -> None:
        current_heads: set = set(initial_heads)
        for rev in revisions:
            current_heads = self._validate_revision(rev, current_heads, revisions_pending_merge)

    @staticmethod
    def _print_banner(title: str) -> None:
        print(SEPARATOR)
        print(title)
        print(SEPARATOR)
        print()

    def _check_permission(self) -> bool:
        print("Checking CREATE DATABASE permission...")
        if not self.sandbox_db._check_permission_safe():
            print("✗ Permission denied.")
            print()
            print("The current database user does not have CREATE DATABASE permission.")
            return False
        print("✓ Permission granted.")
        print()
        return True

    def _create_sandbox_database(self) -> None:
        print("Creating temporary validation database...")
        print(f"Database: {self.sandbox_db.database_name}")
        self.sandbox_db.create_database()
        print("✓ Database created.")
        print()

    def _drop_sandbox_database_safe(self) -> bool:
        try:
            self.sandbox_db.drop_database()
            print("✓ Database dropped.")
            return True
        except Exception:
            print()
            print("⚠ Warning")
            print()
            print("Failed to remove temporary database:")
            print(self.sandbox_db.database_name)
            print()
            print("Please remove it manually before running migrations again.")
            return False

    def _print_result(self, success: bool) -> None:
        if success:
            print(f"Strict validation completed successfully ({len(self.results)} revisions validated).")
        else:
            print("Strict migration validation failed.")
            if self.failed_revision:
                print(f"Failed at revision: {self.failed_revision}")
            print()
            print("The real database was NOT modified.")

    def validate(self, only_new: bool = False) -> bool:
        started_at = time.monotonic()
        self._print_banner(
            "Strict Migration Validation (new migrations only)"
            if only_new else
            "Strict Migration Validation"
        )

        if not self._check_permission():
            self.duration = time.monotonic() - started_at
            return False

        revisions = self.graph.get_revisions()
        revisions_pending_merge = self._find_revisions_pending_merge(revisions)

        real_database_heads: set = set()
        revisions_to_validate = revisions

        if only_new:
            real_database_heads = self._get_real_database_applied_revisions()
            already_applied_closure = self._ancestor_closure(revisions, real_database_heads)
            revisions_to_validate = [r for r in revisions if r.revision not in already_applied_closure]

            print(f"Current database is at revision(s): {', '.join(sorted(real_database_heads))}")
            print(f"{len(revisions_to_validate)} new revision(s) to validate.")
            print()

        success = True
        sandbox_created = False

        try:
            self._create_sandbox_database()
            sandbox_created = True

            if only_new:
                self._seed_sandbox_from_real_database(real_database_heads)

            self._validate_all_revisions(revisions_to_validate, revisions_pending_merge, initial_heads=real_database_heads)
        except _ValidationFailure as failure:
            self.failed_revision = failure.revision_id
            success = False
        finally:
            print()
            print("Cleaning up validation database...")
            if sandbox_created and not self._drop_sandbox_database_safe():
                success = False
            print()

        self.duration = time.monotonic() - started_at
        self._print_result(success)

        return success

    def validate_against_revision(self, target: str) -> bool:
        started_at = time.monotonic()
        self._print_banner(f"Strict Migration Validation (target revision: {target})")

        if not self._check_permission():
            self.duration = time.monotonic() - started_at
            return False

        revisions = self.graph.get_revisions()
        revisions_by_id = {r.revision: r for r in revisions}

        if target not in revisions_by_id:
            print(f"✗ Unknown revision: {target}")
            self.duration = time.monotonic() - started_at
            return False

        revisions_pending_merge = self._find_revisions_pending_merge(revisions)
        current_frontier = self._get_real_database_applied_revisions()

        print(f"Current database is at revision(s): {', '.join(sorted(current_frontier))}")
        print(f"Target revision: {target}")
        print()

        if current_frontier == {target}:
            print("Target revision is already the current revision -- nothing to validate.")
            self.duration = time.monotonic() - started_at
            self._print_result(True)
            return True

        ancestors_of_current = self._ancestor_closure(revisions, current_frontier)
        ancestors_of_target = self._ancestor_closure(revisions, {target})

        seed_frontier = None

        if target in ancestors_of_current:
            safe_trunk = ancestors_of_target - revisions_pending_merge
            seed_frontier = self._frontier_of(revisions, safe_trunk)
            revisions_to_validate = [r for r in revisions if r.revision not in safe_trunk]
        elif current_frontier <= ancestors_of_target:
            revisions_to_validate = [
                r for r in revisions
                if r.revision in (ancestors_of_target - ancestors_of_current)
            ]
        else:
            print(
                f"✗ Revision '{target}' is not reachable from the current "
                f"revision(s) {sorted(current_frontier)} (unrelated branch?)."
            )
            self.duration = time.monotonic() - started_at
            return False

        print(f"{len(revisions_to_validate)} revision(s) to validate.")
        print()

        success = True
        sandbox_created = False

        try:
            self._create_sandbox_database()
            sandbox_created = True

            self._seed_sandbox_from_real_database(current_frontier)

            initial_heads = current_frontier
            if seed_frontier is not None:
                print(f"Downgrading validation database to revision(s): {', '.join(sorted(seed_frontier))}...")
                self._downgrade_sandbox_to_frontier(seed_frontier)
                print("✓ Downgraded.")
                print()
                initial_heads = seed_frontier

            self._validate_all_revisions(revisions_to_validate, revisions_pending_merge, initial_heads=initial_heads)
        except _ValidationFailure as failure:
            self.failed_revision = failure.revision_id
            success = False
        finally:
            print()
            print("Cleaning up validation database...")
            if sandbox_created and not self._drop_sandbox_database_safe():
                success = False
            print()

        self.duration = time.monotonic() - started_at
        self._print_result(success)

        return success
