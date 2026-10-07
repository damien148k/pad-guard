"""Non-drop-frame SMPTE timecode helpers (HH:MM:SS:FF)."""

from __future__ import annotations

import re

TC_RE = re.compile(r"^(\d{2}):([0-5]\d):([0-5]\d)([:;])(\d{2})$")


def is_valid(tc: str, fps: int = 25) -> bool:
    m = TC_RE.match(tc)
    return bool(m) and int(m.group(1)) < 24 and int(m.group(5)) < fps


def is_drop_frame(tc: str) -> bool:
    """Drop-frame timecodes use ';' (or '.') before the frame field."""
    return ";" in tc or "." in tc


def to_frames(tc: str, fps: int = 25) -> int:
    m = TC_RE.match(tc)
    if not m or not is_valid(tc, fps):
        raise ValueError(f"timecode invalide : {tc!r} (attendu HH:MM:SS:FF à {fps} i/s)")
    if m.group(4) == ";":
        raise ValueError(f"timecode drop frame non pris en charge : {tc!r}")
    h, mi, s, f = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(5))
    return ((h * 60 + mi) * 60 + s) * fps + f


def from_frames(frames: int, fps: int = 25) -> str:
    frames %= 24 * 3600 * fps
    f = frames % fps
    s = frames // fps
    return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}:{f:02d}"
