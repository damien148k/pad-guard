"""Files of an analysis directory (``--out``) and their loading, with user-facing errors.

Each step reads the JSON written by the steps before it, so that any step can be rerun alone
(``pad-checker rerun``): probe -> measure -> structure -> rules -> report.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel, ValidationError

PROBE = "probe.json"
MEASUREMENTS = "measurements.json"
STRUCTURE = "structure.json"
EVENTS = "events.json"
VERDICT = "verdict.json"
RUN = "run.json"
PROFILE = "profile.yaml"  # byte copy of the profile file used
EFFECTIVE_PROFILE = "effective_profile.json"  # profile + inherited norms, read by ``rerun`` (SPEC §12.3)
REPORT_MD = "rapport.md"
REPORT_PDF = "rapport.pdf"
THUMBNAILS = "vignettes"
CHARTS = "annexes"

M = TypeVar("M", bound=BaseModel)
Step = Literal["structure", "rules", "report"]


class Rerun(BaseModel):
    at: str
    command: str
    from_step: Step
    profile_file: str


class RunInfo(BaseModel):
    """run.json: when and how the analysis was made. Not a measurement file: it holds dates."""

    analyzed_at: str
    command: str
    profile_file: str
    reruns: list[Rerun] = []


class WorkdirError(Exception):
    """A step cannot read what the previous steps wrote. The message is user-facing (French)."""


def load(workdir: Path, name: str, model: type[M], produced_by: str) -> M:
    path = workdir / name
    if not path.is_file():
        raise WorkdirError(f"{name} absent de {workdir} : lancer d'abord l'étape « {produced_by} »")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise WorkdirError(f"{name} n'est pas un JSON valide ({exc}) : relancer l'étape « {produced_by} »") from None
    field = model.model_fields.get("schema_version")
    if field is not None and isinstance(raw, dict) and raw.get("schema_version") != field.default:
        raise WorkdirError(
            f"{name} est au format {raw.get('schema_version')}, cette version de pad-checker attend le "
            f"format {field.default} : relancer l'étape « {produced_by} »"
        )
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        loc = ".".join(str(x) for x in exc.errors()[0]["loc"])
        raise WorkdirError(
            f"{name} illisible (champ « {loc} ») : fichier produit par une autre version de pad-checker ? "
            f"Relancer l'étape « {produced_by} »"
        ) from None
