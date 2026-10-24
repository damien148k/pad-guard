"""Data model of probe.json (SPEC §4)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from pad_guard.audio_map import AudioMap
from pad_guard.timecode import TimecodeFormat

SCHEMA_VERSION = 1

CheckStatus = Literal["ok", "fail", "unknown"]


class SourceInfo(BaseModel):
    path: str
    size_bytes: int
    sha256: str


class ProfileRef(BaseModel):
    name: str
    version: str
    sha256: str  # of the profile YAML file
    status: Literal["draft", "validated"] | None = None
    effective_sha256: str | None = None  # fingerprint of the effective profile (SPEC §12.3)


class ContainerInfo(BaseModel):
    format_name: str
    kind: Literal["mov", "mxf", "other"]
    duration_s: float | None


class VideoInfo(BaseModel):
    stream_index: int
    codec_name: str
    profile: str | None
    pix_fmt: str | None
    width: int
    height: int
    r_frame_rate: str
    avg_frame_rate: str
    fps: str | None = None  # r_frame_rate as an exact reduced fraction ("25/1", "30000/1001"); None: unreadable
    field_order: str | None
    scan_flag: Literal["progressive", "interlaced", "unknown"] = "unknown"  # what field_order declares
    color_primaries: str | None
    color_transfer: str | None
    color_space: str | None
    color_range: str | None
    duration_s: float | None
    nb_frames: int | None
    # "stream": header frame count; "duration": derived from the stream duration (MXF has no count).
    nb_frames_source: Literal["stream", "duration"] | None


class AudioStreamInfo(BaseModel):
    stream_index: int
    codec_name: str
    sample_rate: int | None
    channels: int
    channel_layout: str | None
    bit_depth: int | None
    duration_s: float | None


class AudioTrack(BaseModel):
    """Profile track number (1-based, across all audio streams) -> (stream, channel in stream)."""

    track: int
    stream_index: int
    channel: int


class Check(BaseModel):
    id: str
    label: str
    # Anomaly type used by the rules engine to pick the severity (profile rules.severity).
    type: str
    expected: str
    actual: str
    status: CheckStatus
    # A failed refusal check stops the analysis: the file is not a supported master.
    refusal: bool = False


class ProbeResult(BaseModel):
    schema_version: int = SCHEMA_VERSION
    tool_version: str
    profile: ProfileRef
    source: SourceInfo
    container: ContainerInfo
    video: VideoInfo
    audio_streams: list[AudioStreamInfo]
    audio_tracks: list[AudioTrack]
    # Track groups used for this analysis (profile default or --audio-map), read by the next steps.
    audio_map: AudioMap
    timecode: str | None
    timecode_source: str | None
    # How the timecode counts (base, drop frame, frames per count): read in the file, else deduced.
    timecode_format: TimecodeFormat | None = None
    checks: list[Check]
    accepted: bool
    refusal_reasons: list[str]
