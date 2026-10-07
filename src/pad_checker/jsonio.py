"""Deterministic JSON output for the pipeline files (probe.json, measurements.json...)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

M = TypeVar("M", bound=BaseModel)


def dumps(model: BaseModel) -> str:
    # Field order comes from the model definition; no timestamps, no dict reordering.
    return json.dumps(model.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"


def write(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(model), encoding="utf-8", newline="\n")


def read(path: Path, model_type: type[M]) -> M:
    return model_type.model_validate_json(path.read_text(encoding="utf-8"))
