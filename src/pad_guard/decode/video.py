"""Frame-by-frame video decoding with PyAV (SPEC §5.1).

Planes are exposed as ``uint16`` arrays in the layout of the file (4:2:0, 4:2:2 or 4:4:4) without
any resampling. Code values are 10-bit, except for a 12-bit file, measured in 12 bits (decision of
Damien, 24 October 2026: the 10-bit thresholds are multiplied by 4 exactly, ``VideoFrame.scale``);
an 8-bit file is converted to 10 bits (x 4, exact) before any comparison (CLAUDE.md). An alpha
plane is ignored. The decoder also performs the integrity check (CLAUDE.md decision): decoding
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

from pad_guard.formats import LAYOUTS


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


def _plane(plane, width: int, height: int, bits: int) -> np.ndarray:
    # line_size may include padding: view the buffer as rows, then crop. No copy for 10 and 12 bits.
    if bits == 8:
        rows = np.frombuffer(plane, dtype=np.uint8).reshape(height, plane.line_size)
        return rows[:, :width].astype(np.uint16) << 2  # 8-bit code x 4 = 10-bit code, exact
    rows = np.frombuffer(plane, dtype="<u2").reshape(height, plane.line_size // 2)
    return rows[:, :width]


def to_frame(frame, index: int) -> VideoFrame:
    """PyAV frame -> VideoFrame (planes in the layout of the file, see the module docstring)."""
    layout = LAYOUTS.get(frame.format.name)
    if layout is None:
        raise ValueError(f"format de pixel décodé {frame.format.name} : non mesurable par PAD Guard")
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
                    yield to_frame(frame, self._decoded)
                    self._decoded += 1

    @property
    def integrity(self) -> IntegrityReport:
        return IntegrityReport(
            frames_expected=self.frames_expected,
            frames_decoded=self._decoded,
            errors=list(self._errors),
            pts_discontinuities=list(self._pts_gaps),
        )


def read_frames(path: Path, indices: Iterable[int], stream_index: int | None = None) -> Iterator[VideoFrame]:
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
            yield from _scan(container, stream, wanted)
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
                yield from _scan(container, stream, [i for i in wanted if i >= index])
                return
            yield _to_frame(frame, index)


def _scan(container, stream, wanted: list[int]) -> Iterator[VideoFrame]:
    container.seek(0, stream=stream, backward=True, any_frame=False)
    pending = iter(wanted)
    target = next(pending, None)
    for index, frame in enumerate(container.decode(stream)):
        if target is None:
            return
        if index == target:
            yield _to_frame(frame, index)
            target = next(pending, None)


_to_frame = to_frame


def _pts_step(stream) -> int | None:
    """Expected pts increment between two frames, in stream time base units."""
    rate = stream.guessed_rate or stream.average_rate
    if not rate or not stream.time_base:
        return None
    step = 1 / (rate * stream.time_base)
    return int(step) if step.denominator == 1 else None
