"""SMPTE timecode (``HH:MM:SS:FF``, drop frame ``HH:MM:SS;FF``) and the frame <-> timecode clock of a file.

A timecode counts in its own base, the number of timecode frames per timecode second, read from
the file (``probe/tc_reader.py``): 24, 25, 30, 50, 60. It is shown as it is stored: a 50p file
whose timecode base is 50 numbers its frames 00 to 49.

Drop frame (bases 30 and 60, rates 29.97 and 59.94): the frame numbers 00 and 01 (00 to 03 in
base 60) are skipped at the start of every minute, except the minutes 00, 10, 20, 30, 40 and 50
(SMPTE ST 12-1), so that the timecode follows the clock.

A file whose timecode base is half its frame rate (50p with a base 25 timecode) counts one
timecode frame per pair of frames: the two frames of a pair carry the same timecode followed by
``PAIR_SUFFIX``.
"""

from __future__ import annotations

import re
from fractions import Fraction

from pydantic import BaseModel

TC_RE = re.compile(r"^(\d{2}):([0-5]\d):([0-5]\d)([:;.,])(\d{2})(\.[12])?$")

# Marks of the first and second frame of a pair when the timecode base is half the frame rate.
# Waiting for Vincent's answer on what his tools show (decision of Damien, 24 October 2026).
PAIR_SUFFIX = (".1", ".2")

_DROP_SEPARATORS = ";.,"


class TimecodeFormat(BaseModel):
    """How the timecode of a file counts (probe.json, structure.json)."""

    base: int  # timecode frames per timecode second
    drop_frame: bool
    frames_per_count: int = 1  # video frames per timecode frame (2: 50p file, base 25 timecode)
    # Where it was read: "tmcd" (MOV/MP4 timecode track), "mxf" (TimecodeComponent), or
    # "cadence" (not readable: deduced from the frame rate and the timecode text).
    source: str = "cadence"


_SOURCES = {"tmcd": "lu dans la piste timecode", "mxf": "lu dans le TimecodeComponent MXF",
            "cadence": "non lu dans le fichier : déduit de la cadence"}


def describe(fmt: TimecodeFormat) -> str:
    """French: 'base 25, non drop frame (lu dans la piste timecode)'."""
    text = f"base {fmt.base}, {'drop frame' if fmt.drop_frame else 'non drop frame'}"
    if fmt.frames_per_count == 2:
        text += f", une valeur pour deux images (suffixes {PAIR_SUFFIX[0]} et {PAIR_SUFFIX[1]})"
    return f"{text} ({_SOURCES.get(fmt.source, fmt.source)})"


def default_format(fps: Fraction | int, tc: str | None = None) -> TimecodeFormat:
    """Format deduced from the frame rate (and the separator of ``tc``) when the file says nothing."""
    base = round(Fraction(fps))
    return TimecodeFormat(base=base, drop_frame=bool(tc) and is_drop_frame(tc) and base in (30, 60))


def _fmt(fmt: TimecodeFormat | int) -> TimecodeFormat:
    return fmt if isinstance(fmt, TimecodeFormat) else TimecodeFormat(base=fmt, drop_frame=False)


def _dropped(fmt: TimecodeFormat) -> int:
    """Frame numbers skipped at the start of a minute in drop frame (2 in base 30, 4 in base 60)."""
    return fmt.base // 15 if fmt.drop_frame else 0


def is_drop_frame(tc: str) -> bool:
    """Drop-frame timecodes use ';' (or '.', ',') before the frame field."""
    m = TC_RE.match(tc)
    return bool(m) and m.group(4) in _DROP_SEPARATORS


def is_valid(tc: str, fmt: TimecodeFormat | int) -> bool:
    """``tc`` is a timecode of this format (the pair suffix only when frames go by pairs)."""
    fmt = _fmt(fmt)
    m = TC_RE.match(tc)
    if not m or int(m.group(1)) >= 24 or int(m.group(5)) >= fmt.base:
        return False
    if m.group(6) and fmt.frames_per_count != 2:
        return False
    drop = _dropped(fmt)
    if drop and int(m.group(3)) == 0 and int(m.group(2)) % 10 and int(m.group(5)) < drop:
        return False  # a skipped number
    return True


def to_count(tc: str, fmt: TimecodeFormat | int) -> int:
    """Timecode frames from 00:00:00:00 to ``tc`` (the pair suffix is ignored)."""
    fmt = _fmt(fmt)
    m = TC_RE.match(tc)
    if not m or not is_valid(tc, fmt):
        kind = "drop frame" if fmt.drop_frame else "non drop frame"
        raise ValueError(f"timecode invalide : {tc!r} (attendu HH:MM:SS:FF en base {fmt.base}, {kind})")
    if m.group(4) in _DROP_SEPARATORS and not fmt.drop_frame:
        raise ValueError(f"timecode drop frame {tc!r} pour un timecode non drop frame (base {fmt.base})")
    h, mi, s, f = int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(5))
    minutes = h * 60 + mi
    return (minutes * 60 + s) * fmt.base + f - _dropped(fmt) * (minutes - minutes // 10)


def from_count(count: int, fmt: TimecodeFormat | int) -> str:
    fmt = _fmt(fmt)
    drop = _dropped(fmt)
    if drop:
        per_10min = fmt.base * 600 - 9 * drop
        per_min = fmt.base * 60 - drop
        count %= 144 * per_10min  # 24 hours
        tens, rest = divmod(count, per_10min)
        # The first minute of a ten-minute block keeps all its numbers.
        count += 9 * drop * tens + (drop * ((rest - drop) // per_min) if rest > drop else 0)
    else:
        count %= 24 * 3600 * fmt.base
    f = count % fmt.base
    s = count // fmt.base
    sep = ";" if fmt.drop_frame else ":"
    return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}{sep}{f:02d}"


# Non drop frame helpers with an integer base (profile timecodes, tests).

def to_frames(tc: str, fps: int) -> int:
    return to_count(tc, TimecodeFormat(base=fps, drop_frame=False))


def from_frames(frames: int, fps: int) -> str:
    return from_count(frames, TimecodeFormat(base=fps, drop_frame=False))


def usable(tc: str | None, fmt: TimecodeFormat | int) -> str | None:
    """``tc`` if it can number the frames of a file in this format, else None."""
    fmt = _fmt(fmt)
    if not tc or not is_valid(tc, fmt) or (is_drop_frame(tc) and not fmt.drop_frame):
        return None
    return tc


class Clock:
    """Frame number <-> timecode of a file, from its start timecode (00:00:00:00 if unusable).

    ``fps`` is the frame rate of the file (exact fraction): durations in seconds use it, never
    the timecode base (23.976 frames/s counts 24 timecode frames per timecode second).
    """

    def __init__(self, fps: Fraction | int, start_tc: str | None, fmt: TimecodeFormat | None = None):
        self.rate = Fraction(fps)
        self.format = fmt or default_format(self.rate, start_tc)
        self.start_tc = usable(start_tc, self.format)
        self.start = self.absolute(self.start_tc) if self.start_tc else 0

    @property
    def pairs(self) -> bool:
        return self.format.frames_per_count == 2

    def absolute(self, tc: str) -> int:
        """Frames from 00:00:00:00 to ``tc`` (first frame of a pair without suffix)."""
        m = TC_RE.match(tc)
        if m and m.group(6) and not self.pairs:
            raise ValueError(f"timecode {tc!r} : suffixe de paire d'images sans objet pour ce fichier")
        phase = PAIR_SUFFIX.index(m.group(6)) if m and m.group(6) else 0
        bare = tc[: len(tc) - len(m.group(6))] if m and m.group(6) else tc
        return to_count(bare, self.format) * self.format.frames_per_count + phase

    def tc(self, frame: int) -> str:
        count, phase = divmod(self.start + frame, self.format.frames_per_count)
        text = from_count(count, self.format)
        return text + PAIR_SUFFIX[phase] if self.pairs else text

    def frame(self, tc: str) -> int:
        """Frame of the file at timecode ``tc`` (negative: before the first frame)."""
        return self.absolute(tc) - self.start

    def duration(self, frames: int) -> str:
        """``frames`` written as a timecode duration in the format of the file."""
        count, phase = divmod(frames, self.format.frames_per_count)
        text = from_count(count, self.format)
        return f"{text} + 1 image" if phase else text

    def seconds(self, frames: int) -> float:
        return float(frames / self.rate)

    def frames_in(self, seconds: float) -> int:
        """Nearest whole number of frames in ``seconds`` at the rate of the file."""
        return round(Fraction(str(seconds)) * self.rate)
