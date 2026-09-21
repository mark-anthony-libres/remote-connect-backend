from __future__ import annotations

import re
import textwrap
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from run.migration_test import Revision

_DATE_ID_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})_(\d{2})_(\d{2})$")
_SANITIZE_RE = re.compile(r"[\"'()\[\]{}:;|<>&#]")

_TEMPLATE_ENV = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "template"),
    autoescape=False,
)

_CLASS_DEFS = """    classDef branch fill:#fde68a,stroke:#b45309,color:#1a1a1a,stroke-width:2px;
    classDef merge fill:#fbbf24,stroke:#92400e,color:#1a1a1a,stroke-width:2px;
    classDef head fill:#86efac,stroke:#15803d,color:#1a1a1a,stroke-width:2px;
    classDef current fill:#60a5fa,stroke:#1d4ed8,color:#0b1220,stroke-width:3px;"""


def fetch_current_db_revisions(config_path: str = "infra/alembic.ini") -> set[str]:
    try:
        from alembic.config import Config
        import psycopg2
        from apps.app.core.settings import settings

        version_table = Config(config_path).get_main_option("version_table") or "alembic_version"
        connection = psycopg2.connect(
            host=settings.pg_db_host,
            port=settings.pg_db_port,
            dbname=settings.pg_db_name,
            user=settings.pg_db_user,
            password=settings.pg_db_password,
        )
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT version_num FROM {version_table}")
                return {row[0] for row in cursor.fetchall()}
        finally:
            connection.close()
    except Exception:
        return set()


def _node_id(revision: str) -> str:
    return "r" + revision.replace("-", "_")


def _short_id(revision: str) -> str:
    match = _DATE_ID_RE.match(revision)
    if not match:
        return revision
    _, month, day, hour, minute = match.groups()
    return f"{month}.{day} {hour}:{minute}"


def _clean_doc(doc: str | None) -> str:
    if not doc or not doc.strip():
        return ""
    first_line = doc.strip().splitlines()[0]
    return _SANITIZE_RE.sub("", first_line).strip()


def _node_label(rev: Revision, current_revisions: set[str]) -> str:
    sid = _short_id(rev.revision)
    if rev.revision in current_revisions:
        sid = f"▶ DB HEAD<br/>{sid}"
    doc = _clean_doc(rev.doc)
    if doc:
        wrapped = "<br/>".join(textwrap.wrap(doc, width=18))
        text = f"{sid}<br/>{wrapped}"
    else:
        text = sid
    return f'{_node_id(rev.revision)}["{text}"]'


def _node_class(rev: Revision, current_revisions: set[str]) -> str | None:
    if rev.revision in current_revisions:
        return "current"
    if rev.is_head:
        return "head"
    if rev.is_merge_point:
        return "merge"
    if rev.is_branch_point:
        return "branch"
    return None


def build_mermaid(revisions: list[Revision], current_revisions: set[str] = frozenset()) -> str:
    lines = [
        "%%{init: {'flowchart': {'nodeSpacing': 20, 'rankSpacing': 30}}}%%",
        "flowchart TD",
    ]
    for rev in revisions:
        lines.append("    " + _node_label(rev, current_revisions))
    for rev in revisions:
        for down in rev.down_revision:
            lines.append(f"    {_node_id(down)} --> {_node_id(rev.revision)}")

    by_class: dict[str, list[str]] = {}
    for rev in revisions:
        cls = _node_class(rev, current_revisions)
        if cls:
            by_class.setdefault(cls, []).append(_node_id(rev.revision))
    if by_class:
        lines.append(_CLASS_DEFS)
        for cls, node_ids in by_class.items():
            lines.append(f"    class {','.join(node_ids)} {cls};")
    return "\n".join(lines)


def render_html(revisions: list[Revision], project_name: str) -> str:
    heads = [r for r in revisions if r.is_head]
    branch_points = [r for r in revisions if r.is_branch_point]
    merge_points = [r for r in revisions if r.is_merge_point]
    current_revisions = fetch_current_db_revisions()
    mermaid_text = build_mermaid(revisions, current_revisions)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")
    db_status = (
        f"DB currently at: {', '.join(sorted(current_revisions))}"
        if current_revisions else
        "DB current revision: unavailable (not connected/not yet migrated)"
    )

    template = _TEMPLATE_ENV.get_template("migration_graph.html")
    return template.render(
        project_name=project_name,
        revision_count=len(revisions),
        branch_point_count=len(branch_points),
        merge_point_count=len(merge_points),
        head_count=len(heads),
        generated_at=generated_at,
        db_status=db_status,
        mermaid_text=mermaid_text,
    )
