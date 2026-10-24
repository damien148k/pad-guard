"""How the start timecode of a file counts: base, drop frame, video frames per timecode frame.

ffprobe gives the start timecode as text in the base of the timecode track, without saying which
base: a 50p file whose timecode track counts 25 frames per second prints ``10:00:00:15`` like a
25p file (checked on FFmpeg 9 fixtures, 24 October 2026). The base is read here from the file
itself, without decoding anything:

* MOV / MP4: the sample description of the ``tmcd`` track (QuickTime File Format, « Timecode
  sample description »): flags (bit 0 drop frame), time scale, frame duration, number of frames;
* MXF: the TimecodeComponent sets of the header metadata (SMPTE ST 377-1): rounded timecode
  base (local tag 15.02), drop frame (15.03), start timecode (15.01).

Only the header boxes and sets are read (a seek over the essence), so a 200 GB master costs a
few reads. Any reading problem gives None: the format is then deduced from the frame rate.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from pad_guard import timecode
from pad_guard.timecode import TimecodeFormat

_MOV_CONTAINERS = {b"moov", b"trak", b"mdia", b"minf", b"stbl"}
_MXF_PREFIX = bytes.fromhex("060e2b34")
_TIMECODE_COMPONENT = bytes.fromhex("060e2b34025301010d01010101011400")
_ESSENCE = bytes.fromhex("060e2b34010201010d010301")  # generic container essence element
_MXF_SCAN_BYTES = 64 << 20  # header metadata is at the start of the file, before the essence


@dataclass(frozen=True)
class _Timecode:
    base: int
    drop_frame: bool
    frame_duration_s: Fraction | None  # duration of one timecode frame (MOV), None: one video frame
    start: int | None  # start in timecode frames, when the file stores it here


def read_format(path: Path, kind: str, fps: Fraction, tc: str | None) -> TimecodeFormat | None:
    """Timecode format of the file (``kind``: container kind of probe.json), None if unreadable."""
    try:
        with path.open("rb") as f:
            found = _mxf(f) if kind == "mxf" else _mov(f)
    except (OSError, struct.error, ValueError):
        return None
    if not found:
        return None
    pick = found[0]
    if tc:  # several components (MXF material and source packages): the one ffprobe reported
        for t in found:
            fmt = TimecodeFormat(base=t.base, drop_frame=t.drop_frame)
            if t.start is not None and timecode.is_valid(tc, fmt) and timecode.usable(tc, fmt) \
                    and timecode.to_count(tc, fmt) == t.start:
                pick = t
                break
    if pick.base <= 0:
        return None
    per_count = (pick.frame_duration_s * fps) if pick.frame_duration_s is not None else Fraction(fps, pick.base)
    frames_per_count = 2 if round(per_count) == 2 else 1
    return TimecodeFormat(base=pick.base, drop_frame=pick.drop_frame, frames_per_count=frames_per_count,
                          source="mxf" if kind == "mxf" else "tmcd")


# --- MOV / MP4 ----------------------------------------------------------------------------------


def _boxes(f, start: int, end: int):
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        size, kind = struct.unpack(">I4s", f.read(8))
        header = 8
        if size == 1:
            size = struct.unpack(">Q", f.read(8))[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header:
            raise ValueError("boîte MOV invalide")
        yield kind, pos + header, pos + size
        pos += size


def _mov(f) -> list[_Timecode]:
    f.seek(0, 2)
    size = f.tell()
    out: list[_Timecode] = []

    def walk(start: int, end: int) -> None:
        for kind, body, stop in _boxes(f, start, end):
            if kind in _MOV_CONTAINERS:
                walk(body, stop)
            elif kind == b"stsd":
                f.seek(body + 8)  # version, flags, entry count
                entry = f.read(34)
                if entry[4:8] == b"tmcd":
                    # size, format, 6 reserved, data reference index, 4 reserved, flags, time scale,
                    # frame duration, number of frames
                    flags, scale, duration, frames = struct.unpack(">IIIB", entry[20:33])
                    out.append(_Timecode(base=frames, drop_frame=bool(flags & 1),
                                         frame_duration_s=Fraction(duration, scale) if scale else None, start=None))

    walk(0, size)
    return out


# --- MXF ----------------------------------------------------------------------------------------


def _ber(f) -> int:
    first = f.read(1)
    if not first:
        raise ValueError("fin de fichier")
    n = first[0]
    if n < 0x80:
        return n
    return int.from_bytes(f.read(n & 0x7F), "big")


def _mxf(f) -> list[_Timecode]:
    out: list[_Timecode] = []
    pos = 0
    while pos < _MXF_SCAN_BYTES:
        f.seek(pos)
        key = f.read(16)
        if len(key) < 16 or not key.startswith(_MXF_PREFIX):
            break
        length = _ber(f)
        body = f.tell()
        if key.startswith(_ESSENCE):
            break
        if key == _TIMECODE_COMPONENT:
            out.append(_component(f.read(length)))
        pos = body + length
    return out


def _component(data: bytes) -> _Timecode:
    base, drop, start = 0, False, None
    i = 0
    while i + 4 <= len(data):
        tag, size = struct.unpack(">HH", data[i:i + 4])
        value = data[i + 4:i + 4 + size]
        if tag == 0x1502:
            base = struct.unpack(">H", value)[0]
        elif tag == 0x1503:
            drop = value[:1] != b"\x00"
        elif tag == 0x1501:
            start = struct.unpack(">q", value)[0]
        i += 4 + size
    return _Timecode(base=base, drop_frame=drop, frame_duration_s=None, start=start)
