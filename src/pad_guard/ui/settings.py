"""Local settings of the interface (reglages.json): where the analyses go.

Default file: ``%APPDATA%\\PAD Guard\\reglages.json`` (``PAD_GUARD_SETTINGS`` overrides it, for the
tests). Default analyses root: ``%USERPROFILE%\\Documents\\PAD Guard\\analyses``, never the repository.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from pydantic import BaseModel


def settings_path() -> Path:
    if os.environ.get("PAD_GUARD_SETTINGS"):
        return Path(os.environ["PAD_GUARD_SETTINGS"])
    base = Path(os.environ.get("APPDATA") or Path.home() / ".config")
    return base / "PAD Guard" / "reglages.json"


def default_root() -> Path:
    return Path.home() / "Documents" / "PAD Guard" / "analyses"


class Settings(BaseModel):
    analyses_root: str = ""

    @property
    def root(self) -> Path:
        return Path(self.analyses_root) if self.analyses_root else default_root()


def load(path: Path | None = None) -> Settings:
    path = path or settings_path()
    if not path.is_file():
        return Settings(analyses_root=str(default_root()))
    try:
        return Settings.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, ValueError):
        return Settings(analyses_root=str(default_root()))


def save(settings: Settings, path: Path | None = None) -> None:
    path = path or settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(settings.model_dump_json(indent=2) + "\n", encoding="utf-8")
