"""Data model of events.json and verdict.json (SPEC §7)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from pad_guard.probe.models import ProfileRef
from pad_guard.rules.profile import Severity

# 2: severity_source on every event.
SCHEMA_VERSION = 2


class Event(BaseModel):
    """A continuous range of frames sharing one anomaly (SPEC §7.1)."""

    id: int  # 1-based, in chronological order
    type: str
    severity: Severity
    severity_source: str  # source of the profile rule that gave the severity ("Arte §3.2.3.3", "DEDUIT"...)
    title: str  # French, what is wrong
    source: Literal["probe", "measure", "structure", "integrity", "delivery"]
    scope: Literal["range", "file"]  # file: a property of the whole file (codec, loudness...)
    frame_start: int
    frame_end: int  # inclusive
    tc_start: str
    tc_end: str
    duration_frames: int
    worst_value: float | None
    worst_frame: int | None
    threshold: float | None
    area_pct_max: float | None
    value_text: str  # French display of worst_value, with unit
    threshold_text: str
    group: str | None = None  # audio group or track
    detail: str = ""
    occurrences: int | None = None  # integrity: number of decoding errors merged into this event

    @property
    def key(self) -> str:
        """Stable name of the anomaly across reruns (the id is a rank, it moves): type, first frame, group."""
        return f"{self.type}@{self.frame_start}@{self.group or ''}"


class Events(BaseModel):
    schema_version: int = SCHEMA_VERSION
    tool_version: str
    profile: ProfileRef
    source_sha256: str
    events: list[Event]


class Verdict(BaseModel):
    schema_version: int = SCHEMA_VERSION
    tool_version: str
    profile: ProfileRef
    source_sha256: str
    status: Literal["CONFORME", "NON-CONFORME"]
    score: float
    score_formula: str
    counts: dict[Severity, int]
    max_major: int
    reasons: list[str]  # French, why NON-CONFORME (empty when CONFORME)
    # Profile in meta.status draft: the status above is computed as usual, but the report shows
    # it only as indicative and never says CONFORME (CLAUDE.md principle 7).
    indicative: bool = False
