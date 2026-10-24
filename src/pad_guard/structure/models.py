"""Data model of structure.json (SPEC §6)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from pad_guard.probe.models import CheckStatus, ProfileRef
from pad_guard.timecode import TimecodeFormat

SCHEMA_VERSION = 1


class FrameRange(BaseModel):
    frame_start: int
    frame_end: int  # inclusive

    @property
    def frames(self) -> int:
        return self.frame_end - self.frame_start + 1


class StructureCheck(BaseModel):
    """One line of the "format and structure" table. A failed check becomes an event of ``type``."""

    id: str
    label: str
    type: str
    expected: str
    actual: str
    status: CheckStatus
    frame_start: int | None = None  # frames concerned (None: the whole file)
    frame_end: int | None = None
    worst_value: float | None = None
    threshold: float | None = None


class Finding(BaseModel):
    """A range of frames with an anomaly found by a structure detector (freeze, PSE...)."""

    type: str
    frame_start: int
    frame_end: int
    worst_value: float | None
    worst_frame: int | None
    threshold: float | None
    detail: str


class BarsRange(BaseModel):
    frame_start: int
    frame_end: int
    pattern: str
    tested_frame: int
    error: float  # median absolute error per region, worst plane, 10-bit code values


class ToneMeasure(BaseModel):
    track: int
    frequency_hz: float | None  # dominant frequency (None: silence)
    level_dbfs: float | None  # sine-referenced RMS level (RMS + 3.01 dB)


class LetterboxSample(BaseModel):
    frame: int
    top: int  # first and last active rows / columns, 0-based
    bottom: int
    left: int
    right: int


class LetterboxSummary(BaseModel):
    sample_seconds: float
    samples: list[LetterboxSample]
    dominant: LetterboxSample | None
    dominant_share_pct: float
    dominant_aspect: float | None = None  # width / height of the dominant area, pixel aspect ratio included
    matched_format: str | None
    changes: list[str]  # French, information only (SPEC §6.5)


class Structure(BaseModel):
    schema_version: int = SCHEMA_VERSION
    tool_version: str
    profile: ProfileRef
    source_sha256: str
    fps: str
    frames: int
    # Start timecode used for every timecode of the analysis (None: file timecode absent or
    # unusable, timecodes count from 00:00:00:00).
    timecode_start: str | None
    timecode_format: TimecodeFormat | None = None  # None: older structure.json, deduced from the rate
    leaders: Literal["classic", "none"]
    bars: list[BarsRange]
    tone: list[ToneMeasure]
    head_black: FrameRange | None
    tail_black: FrameRange | None
    program: FrameRange
    checks: list[StructureCheck]
    findings: list[Finding]
    letterbox: LetterboxSummary | None
    limitations: list[str]  # French, shown in the report
