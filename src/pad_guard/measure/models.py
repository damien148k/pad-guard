"""Data model of measurements.json (SPEC §5.4).

measurements.json holds the header, the integrity report, the program range and the global
audio values. The per-frame video measurements and the per-block audio measurements are
streamed to two JSON Lines files next to it (``video.file`` and ``audio.file``), whatever the
film length: they are written as they are measured and read back line by line.

Levels in dB use ``None`` for digital silence (-inf is not valid JSON).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from pad_guard.decode.video import IntegrityReport
from pad_guard.probe.models import ProfileRef
from pad_guard.rules.profile import AudioGroup, ScanDetection

# 2: frame differences (d_mean, d_up_pct, d_down_pct) and flash delta in video_settings.
# 3: combing indicator per frame (comb) and scan detection (scan).
SCHEMA_VERSION = 3


class MeasuredSource(BaseModel):
    path: str
    sha256: str
    frames: int | None  # announced by the container (probe.json)
    fps: str


class VideoSettings(BaseModel):
    """Thresholds actually applied, in 10-bit code values (inclusive ranges)."""

    y_legal: tuple[int, int]
    y_tolerance: tuple[int, int]
    rgb: tuple[int, int]
    prefilter_taps: int | None
    matrix: str
    flash_delta_pct: float  # d_up_pct / d_down_pct: relative luminance change above this
    luminance: Literal["bt1886_gamma_2.4"] = "bt1886_gamma_2.4"
    chroma_upsampling: Literal["linear"] = "linear"
    percentiles: Literal["nearest_rank"] = "nearest_rank"


class ScanSummary(BaseModel):
    """Scan declared by the container and scan seen in the pictures (SPEC §12.5)."""

    field_order: str | None  # ffprobe flag
    flag: Literal["progressive", "interlaced", "unknown"]
    detected: Literal["progressive", "interlaced", "undetermined"]
    moving_frames: int
    combed_frames: int
    combed_pct: float | None
    agrees: bool | None  # None: flag unknown or detection undetermined
    settings: ScanDetection


class VideoSection(BaseModel):
    format: Literal["jsonl"] = "jsonl"
    file: str
    fields: list[str]
    frames: int
    # First field of a file flagged interlaced: the field measures (fu1, fd1, fu2, fd2) are written,
    # null for a frame that is not combed and does not follow a combed frame (measure/video.py).
    first_field: Literal["top", "bottom"] | None = None


class ProgramRange(BaseModel):
    """Part of the file treated as programme for the global audio values (SPEC §5.3)."""

    frame_start: int
    frame_end: int  # inclusive
    tc_start: str | None
    tc_end: str | None
    sample_start: int
    sample_end: int  # exclusive
    # file: whole file; timecode: profile program_start located with the file timecode;
    # profile: file timecode unusable, position expected by the profile; black_tail: trailing black removed.
    start_method: Literal["file", "timecode", "profile"]
    end_method: Literal["file", "black_tail"]


class TrackLevels(BaseModel):
    """One audio track (channel) over the programme range."""

    track: int
    stream_index: int
    channel: int
    peak_dbfs: float | None
    true_peak_dbtp: float | None
    rms_dbfs: float | None
    full_scale_samples: int


class GroupLoudness(BaseModel):
    """One track group over the programme range. Loudness by FFmpeg ebur128, peaks by NumPy."""

    group: AudioGroup
    integrated_lufs: float | None  # None: no block above the -70 LUFS absolute gate
    lra_lu: float | None
    momentary_max_lufs: float | None
    short_term_max_lufs: float | None
    true_peak_dbtp: float | None
    sample_peak_dbfs: float | None
    correlation: float | None  # 2-track groups only
    difference_peak_dbfs: float | None  # 2-track groups only: peak of L - R (None = identical)


class AudioSettings(BaseModel):
    sample_rate: int
    block_samples: int
    loudness: Literal["ffmpeg_ebur128"] = "ffmpeg_ebur128"
    true_peak: Literal["bs1770_4x"] = "bs1770_4x"


class AudioSection(BaseModel):
    format: Literal["jsonl"] = "jsonl"
    file: str
    fields: list[str]
    settings: AudioSettings
    program: ProgramRange
    tracks: list[TrackLevels]
    groups: dict[str, GroupLoudness]
    blocks: int
    decode_errors: list[str]


class Measurements(BaseModel):
    schema_version: int = SCHEMA_VERSION
    tool_version: str
    source: MeasuredSource
    profile: ProfileRef
    integrity: IntegrityReport
    video_settings: VideoSettings
    video: VideoSection
    scan: ScanSummary
    audio: AudioSection | None  # None: no audio track in the file
