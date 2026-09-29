"""Load optional repository-local settings without replacing shell values."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DOTENV_PATH = REPO_ROOT / ".env"
DotenvLoader = Callable[..., Any]


def load_repo_dotenv(
    dotenv_path: Path = DEFAULT_DOTENV_PATH,
    *,
    loader: DotenvLoader | None = None,
) -> bool:
    """Load the repo-root .env when present, preserving existing environment values."""

    path = Path(dotenv_path)
    if not path.is_file():
        return False
    if loader is None:
        try:
            from dotenv import load_dotenv
        except ImportError:
            return False
        loader = load_dotenv
    return bool(loader(dotenv_path=path, override=False))
