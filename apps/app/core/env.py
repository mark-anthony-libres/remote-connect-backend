from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


@lru_cache(maxsize=1)
def load_project_env() -> None:
    start = Path(__file__).resolve()
    for parent in (start.parent, *start.parents):
        env_path = parent / ".env"
        if env_path.is_file():
            load_dotenv(dotenv_path=env_path, override=False)
            return
