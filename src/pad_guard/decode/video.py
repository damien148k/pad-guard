"""Frame-by-frame video decoding with PyAV (SPEC §5.1).

Planes are exposed as ``uint16`` arrays in the layout of the file (4:2:0, 4:2:2 or 4:4:4) without
any resampling. Code values are 10-bit, except for a 12-bit file, measured in 12 bits (decision of
Damien, 24 October 2026: the 10-bit thresholds are multiplied by 4 exactly, ``VideoFrame.scale``);
an 8-bit file is converted to 10 bits (x 4, exact) before any comparison (CLAUDE.md). An alpha
plane is ignored.

A full-range file (``color_range`` pc, FFmpeg yuvj*) and an R'G'B' file are converted to narrow
range Y'CbCr before measuring, so that every threshold of the profile (expressed on the narrow
range: black 64, white 940) applies to the right levels. The conversion goes through the signal
values E' of ITU-R BT.2100-3 Table 9 (full range D = Round[(2^n - 1) E'], chroma
D = Round[(2^n - 1) E' + 2^(n-1)]) and ITU-R BT.709-6 part 2 (items 3.2 to 3.4: luma and colour
difference signals, narrow quantization), and lands in 12-bit narrow codes (scale 4) so that
the rounding stays below a quarter of a 10-bit code. The decoder also performs the integrity check (CLAUDE.md decision): decoding
errors are recorded instead of aborting, and the decoded frame count is compared to the
count announced by the container.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

import av
import av.logging
import numpy as np
from pydantic import BaseModel

from pad_guard.formats import LAYOUTS, MATRICES


class DecoderOpenError(Exception):
    """The file cannot be opened by the decoder. The message is user-facing (French)."""


class DecodeError(BaseModel):
    after_frame: int  # number of frames successfully decoded when the error occurred
    message: str


class IntegrityReport(BaseModel):
    frames_expected: int | None
    frames_decoded: int
    errors: list[DecodeError]
    # Frames whose timestamp does not follow the previous one (dropped or duplicated frames in the file).
    pts_discontinuities: list[int]

    @property
    def ok(self) -> bool:
        return (
            not self.errors
            and not self.pts_discontinuities
            and (self.frames_expected is None or self.frames_expected == self.frames_decoded)
        )


@dataclass
class VideoFrame:
    index: int  # absolute frame number, 0 = first frame of the file
    y: np.ndarray  # (height, width) uint16
    cb: np.ndarray  # (height / vsub, width / hsub) uint16
    cr: np.ndarray
    scale: int = 1  # code values per 10-bit code value: 4 for a 12-bit file, else 1
    hsub: int = 2  # chroma subsampling: 4:2:2 = (2, 1), 4:2:0 = (2, 2), 4:4:4 = (1, 1)
    vsub: int = 1

    def as_422_10(self) -> VideoFrame:
        """4:2:2 10-bit view of the frame, for displays and pattern matching (thumbnails, bars).
        The frame itself when it already is; otherwise chroma rows repeated (4:2:0), every other
        chroma sample kept (4:4:4) and 12-bit values divided by 4 (rounded down)."""
        if (self.scale, self.hsub, self.vsub) == (1, 2, 1):
            return self
        shift = self.scale.bit_length() - 1
        h = self.y.shape[0]

        def chroma(plane: np.ndarray) -> np.ndarray:
            if self.vsub == 2:
                plane = np.repeat(plane, 2, axis=0)[:h]
            if self.hsub == 1:
                plane = plane[:, 0::2]
            return plane >> shift if shift else plane

        return VideoFrame(index=self.index, y=self.y >> shift if shift else self.y, cb=chroma(self.cb),
                          cr=chroma(self.cr))


@dataclass(frozen=True)
class Picture:
    """How the decoded planes become the narrow-range Y'CbCr that is measured."""

    full_range: bool  # Y'CbCr or R'G'B' coded on the full range of the bit depth
    matrix: str = "bt709"  # R'G'B' -> Y'CbCr (an R'G'B' file only)


def picture_of(pix_fmt: str | None, color_range: str | None, matrix: str) -> Picture | None:
    """Conversion needed by a file (None: narrow range Y'CbCr, measured as it is)."""
    layout = LAYOUTS.get(pix_fmt or "")
    if layout is None:
        return None
    if layout.rgb:  # R'G'B' is full range unless the file says otherwise
        return Picture(full_range=color_range != "tv", matrix=matrix)
    if layout.full_range or color_range == "pc":
        return Picture(full_range=True, matrix=matrix)
    return None


def _round(x: np.ndarray) -> np.ndarray:
    """Round[x] of BT.2100 (half away from zero) for the positive values here, as uint16."""
    return np.floor(x + 0.5).clip(0, 65535).astype(np.uint16)


def _signal(plane: np.ndarray, bits: int, full_range: bool, chroma: bool) -> np.ndarray:
    """Code values -> E' (float32): luma or R'G'B' in [0, 1], colour difference in [-0.5, 0.5]."""
    d = plane.astype(np.float32)
    if full_range:
        top = np.float32(2 ** bits - 1)
        return (d - np.float32(2 ** (bits - 1))) / top if chroma else d / top
    step = np.float32(2 ** (bits - 8))
    return (d / step - np.float32(128)) / np.float32(224) if chroma else (d / step - np.float32(16)) / np.float32(219)


def _narrow12(e: np.ndarray, chroma: bool) -> np.ndarray:
    """E' -> 12-bit narrow code (BT.709-6 item 3.4 with n = 12)."""
    return _round((e * np.float32(224) + np.float32(128)) * 16) if chroma else _round((e * np.float32(219) + np.float32(16)) * 16)


def _convert(frame, layout, picture: Picture, index: int) -> VideoFrame:
    w, h = frame.width, frame.height
    p = frame.planes
    raw = lambda k, cw, ch: _plane(p[k], cw, ch, layout.bits, keep_bits=True)  # noqa: E731
    if layout.rgb:  # FFmpeg gbrp*: planes G, B, R
        g, b, r = (_signal(raw(k, w, h), layout.bits, picture.full_range, False) for k in range(3))
        kr, kb = MATRICES[picture.matrix]
        ey = np.float32(kr) * r + np.float32(1 - kr - kb) * g + np.float32(kb) * b
        ecb = (b - ey) / np.float32(2 * (1 - kb))  # BT.709-6 item 3.3: (E'B - E'Y) / 1.8556
        ecr = (r - ey) / np.float32(2 * (1 - kr))  # (E'R - E'Y) / 1.5748
        return VideoFrame(index=index, y=_narrow12(ey, False), cb=_narrow12(ecb, True), cr=_narrow12(ecr, True),
                          scale=4, hsub=1, vsub=1)
    cw, ch = -(-w // layout.hsub), -(-h // layout.vsub)
    y = _narrow12(_signal(raw(0, w, h), layout.bits, True, False), False)
    cb = _narrow12(_signal(raw(1, cw, ch), layout.bits, True, True), True)
    cr = _narrow12(_signal(raw(2, cw, ch), layout.bits, True, True), True)
    return VideoFrame(index=index, y=y, cb=cb, cr=cr, scale=4, hsub=layout.hsub, vsub=layout.vsub)


def _plane(plane, width: int, height: int, bits: int, keep_bits: bool = False) -> np.ndarray:
    # line_size may include padding: view the buffer as rows, then crop. No copy for 10 and 12 bits.
    if bits == 8:
        rows = np.frombuffer(plane, dtype=np.uint8).reshape(height, plane.line_size)
        if keep_bits:
            return rows[:, :width]
        return rows[:, :width].astype(np.uint16) << 2  # 8-bit code x 4 = 10-bit code, exact
    rows = np.frombuffer(plane, dtype="<u2").reshape(height, plane.line_size // 2)
    return rows[:, :width]


def to_frame(frame, index: int, picture: Picture | None = None) -> VideoFrame:
    """PyAV frame -> VideoFrame (planes in the layout of the file, see the module docstring)."""
    layout = LAYOUTS.get(frame.format.name)
    if layout is None:
        raise ValueError(f"format de pixel décodé {frame.format.name} : non mesurable par PAD Guard")
    if layout.rgb and picture is None:
        picture = Picture(full_range=True)
    if picture is not None:
        return _convert(frame, layout, picture, index)
    w, h = frame.width, frame.height
    cw, ch = -(-w // layout.hsub), -(-h // layout.vsub)
    p = frame.planes
    return VideoFrame(index=index, y=_plane(p[0], w, h, layout.bits), cb=_plane(p[1], cw, ch, layout.bits),
                      cr=_plane(p[2], cw, ch, layout.bits), scale=4 if layout.bits == 12 else 1,
                      hsub=layout.hsub, vsub=layout.vsub)


@dataclass
class VideoDecoder:
    """Iterate over every frame of the video stream. ``integrity`` is complete once iteration ends."""

    path: Path
    stream_index: int | None = None
    frames_expected: int | None = None
    threads: int = 0  # 0 = FFmpeg picks the number of threads
    picture: Picture | None = None  # full range or R'G'B': converted (see the module docstring)
    _errors: list[DecodeError] = field(default_factory=list, init=False)
    _pts_gaps: list[int] = field(default_factory=list, init=False)
    _decoded: int = field(default=0, init=False)

    def frames(self) -> Iterator[VideoFrame]:
        self._errors.clear()
        self._pts_gaps.clear()
        self._decoded = 0
        # Concealed errors (e.g. a corrupt ProRes slice) are only logged by FFmpeg: capture them.
        av.logging.set_level(av.logging.ERROR)
        try:
            yield from self._decode()
        finally:
            av.logging.set_level(None)

    def _decode(self) -> Iterator[VideoFrame]:
        try:
            container = av.open(str(self.path))
        except av.FFmpegError as exc:
            raise DecoderOpenError(f"impossible d'ouvrir {self.path.name} : {exc}") from None
        with container, av.logging.Capture(local=False) as logs:
            stream = (
                container.streams.video[0]
                if self.stream_index is None
                else next(s for s in container.streams if s.index == self.stream_index)
            )
            stream.thread_type = "AUTO"
            stream.codec_context.thread_count = self.threads
            step = _pts_step(stream)
            last_pts: int | None = None
            seen_logs = 0

            for packet in container.demux(stream):
                try:
                    decoded = stream.decode(packet)
                except av.FFmpegError as exc:
                    self._errors.append(DecodeError(after_frame=self._decoded, message=str(exc)))
                    decoded = []
                if len(logs) > seen_logs:
                    for level, name, message in logs[seen_logs:]:
                        if level <= av.logging.ERROR:
                            text = f"{name}: {message.strip()}" if name else message.strip()
                            self._errors.append(DecodeError(after_frame=self._decoded, message=text))
                    seen_logs = len(logs)
                for frame in decoded:
                    if frame.pts is not None:
                        if last_pts is not None and step and frame.pts - last_pts != step:
                            self._pts_gaps.append(self._decoded)
                        last_pts = frame.pts
                    yield to_frame(frame, self._decoded, self.picture)
                    self._decoded += 1

    @property
    def integrity(self) -> IntegrityReport:
        return IntegrityReport(
            frames_expected=self.frames_expected,
            frames_decoded=self._decoded,
            errors=list(self._errors),
            pts_discontinuities=list(self._pts_gaps),
        )


def read_frames(path: Path, indices: Iterable[int], stream_index: int | None = None,
                picture: Picture | None = None) -> Iterator[VideoFrame]:
    """Decode only the frames at ``indices`` (0 = first frame of the file), in increasing order.

    ProRes and DNxHR are intra-only codecs: a seek lands on the requested frame. The frame
    timestamp is checked, and if seeking is not exact (or the stream has no constant timestamp
    step) the frames are reached by decoding from the start instead. Used by the structure and
    report steps for a few hundred frames at most (bars, letterbox, thumbnails).
    """
    wanted = sorted(set(indices))
    if not wanted:
        return
    try:
        container = av.open(str(path))
    except av.FFmpegError as exc:
        raise DecoderOpenError(f"impossible d'ouvrir {path.name} : {exc}") from None
    with container:
        stream = (
            container.streams.video[0]
            if stream_index is None
            else next(s for s in container.streams if s.index == stream_index)
        )
        stream.thread_type = "AUTO"
        step = _pts_step(stream)
        first = next(container.decode(stream), None)
        if first is None:
            return
        if step is None or first.pts is None:
            yield from _scan(container, stream, wanted, picture)
            return
        for index in wanted:
            target = first.pts + index * step
            container.seek(target, stream=stream, backward=True, any_frame=False)
            frame = None
            for candidate in container.decode(stream):
                if candidate.pts is None or candidate.pts >= target:
                    frame = candidate
                    break
            if frame is None:
                return  # beyond the end of the file
            if frame.pts != target:
                yield from _scan(container, stream, [i for i in wanted if i >= index], picture)
                return
            yield to_frame(frame, index, picture)


def _scan(container, stream, wanted: list[int], picture: Picture | None = None) -> Iterator[VideoFrame]:
    container.seek(0, stream=stream, backward=True, any_frame=False)
    pending = iter(wanted)
    target = next(pending, None)
    for index, frame in enumerate(container.decode(stream)):
        if target is None:
            return
        if index == target:
            yield to_frame(frame, index, picture)
            target = next(pending, None)




def _pts_step(stream) -> int | None:
    """Expected pts increment between two frames, in stream time base units."""
    rate = stream.guessed_rate or stream.average_rate
    if not rate or not stream.time_base:
        return None
    step = 1 / (rate * stream.time_base)
    return int(step) if step.denominator == 1 else None
