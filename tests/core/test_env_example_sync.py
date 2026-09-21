from __future__ import annotations

import re
from pathlib import Path

from apps.app.core.settings import Settings

ENV_EXAMPLE_PATH = Path(__file__).resolve().parents[2] / ".env.example"

NON_SETTINGS_VARS = {"MONITOR_PORT"}


def _settings_env_names() -> set[str]:
    names = set()
    for field_name, field in Settings.model_fields.items():
        alias = field.validation_alias
        names.add(alias if isinstance(alias, str) else field_name.upper())
    return names


def _env_example_names() -> set[str]:
    names = set()
    for line in ENV_EXAMPLE_PATH.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Z0-9_]+)=", line)
        if match:
            names.add(match.group(1))
    return names


def test_env_example_covers_every_settings_field():
    missing = sorted(_settings_env_names() - _env_example_names())
    assert not missing, (
        "settings.py defines these env vars but .env.example is missing them: "
        f"{missing}. Add a line for each in .env.example (see its header for "
        "conventions - JSON array syntax for List[str] fields, blank/placeholder "
        "for secrets)."
    )


def test_env_example_has_no_stray_vars():
    stray = sorted(_env_example_names() - _settings_env_names() - NON_SETTINGS_VARS)
    assert not stray, (
        f".env.example defines these vars that no longer match a settings.py field: "
        f"{stray}. Remove them, or add to NON_SETTINGS_VARS if consumed elsewhere."
    )
