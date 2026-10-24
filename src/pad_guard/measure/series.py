"""Read the JSON Lines measurement files back as NumPy columns (structure and rules steps).

A 90 min film gives about 135 000 frame lines of ~20 numbers and 54 000 audio blocks per group:
a few tens of megabytes as columns, read line by line. Missing values become NaN (frame
differences of the first frame, loudness windows not yet full, undefined correlation) and
digital silence (``None`` in dB) becomes -inf, so that "below a threshold" stays true.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np

from pad_guard.measure.models import Measurements

_SILENCE_DB = ("tp", "peak", "rms", "diff")


@dataclass
class VideoSeries:
    columns: dict[str, np.ndarray]

    @property
    def frames(self) -> int:
        return int(self.columns["f"].shape[0])

    def __getitem__(self, name: str) -> np.ndarray:
        return self.columns[name]


def load_video(workdir: Path, m: Measurements) -> VideoSeries:
    fields = m.video.fields
    values: dict[str, list] = {name: [] for name in fields}
    with (workdir / m.video.file).open(encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            for name in fields:
                v = rec[name]
                values[name].append(math.nan if v is None else v)
    columns = {name: np.asarray(v, dtype=np.float64) for name, v in values.items()}
    if columns["f"].shape[0] != m.video.frames or not np.array_equal(columns["f"], np.arange(m.video.frames)):
        raise ValueError(f"{m.video.file} incomplet ou désordonné : relancer les mesures")
    return VideoSeries(columns)


@dataclass
class GroupBlocks:
    """100 ms blocks of one track group. Per-track columns have shape (blocks, tracks)."""

    t: np.ndarray
    m: np.ndarray  # momentary loudness, LUFS (NaN: window not full)
    s: np.ndarray  # short-term loudness, LUFS
    tp: np.ndarray  # true peak, dBTP (-inf: digital silence)
    peak: np.ndarray
    rms: np.ndarray
    clip: np.ndarray
    corr: np.ndarray  # 2-track groups, NaN otherwise
    diff: np.ndarray  # peak of L - R, dBFS, -inf: identical


def load_audio(workdir: Path, m: Measurements) -> dict[str, GroupBlocks]:
    if m.audio is None:
        return {}
    raw: dict[str, dict[str, list]] = {}
    with (workdir / m.audio.file).open(encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            cols = raw.setdefault(rec["g"], {k: [] for k in m.audio.fields if k != "g"})
            for key, values in cols.items():
                values.append(rec[key])
    out: dict[str, GroupBlocks] = {}
    for name, cols in raw.items():
        conv = {}
        for key, values in cols.items():
            fill = -math.inf if key in _SILENCE_DB else math.nan
            if values and isinstance(values[0], list):
                conv[key] = np.array([[fill if x is None else x for x in row] for row in values], dtype=np.float64)
            else:
                conv[key] = np.array([fill if x is None else x for x in values], dtype=np.float64)
        out[name] = GroupBlocks(**conv)
    return out


def block_frames(block: int, block_samples: int, sample_rate: int, fps: Fraction, frames: int) -> tuple[int, int]:
    """Frames (inclusive) overlapped by audio block ``block``."""
    per_frame = Fraction(sample_rate) / fps
    start = int(Fraction(block * block_samples) / per_frame)
    end = math.ceil(Fraction((block + 1) * block_samples) / per_frame) - 1
    return min(start, frames - 1), min(max(end, start), frames - 1)


def frame_blocks(frame: int, block_samples: int, sample_rate: int, fps: Fraction) -> tuple[int, int]:
    """Audio blocks (inclusive) overlapped by ``frame``."""
    per_frame = Fraction(sample_rate) / fps
    start = int(frame * per_frame / block_samples)
    end = math.ceil((frame + 1) * per_frame / block_samples) - 1
    return start, max(end, start)
