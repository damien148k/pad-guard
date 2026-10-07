"""Frame-by-frame video decoding with PyAV (SPEC §5.1).

Planes are exposed as ``uint16`` arrays (10-bit code values 0-1023) without any format
conversion. The decoder also performs the integrity check (CLAUDE.md decision): decoding
errors are recorded instead of aborting, and the decoded frame count is compared to the
count announced by the container.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import av
import av.logging
import numpy as np
from pydantic import BaseModel

EXPECTED_PIX_FMT = "yuv422p10le"


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
    cb: np.ndarray  # (height, width / 2) uint16
    cr: np.ndarray


def _plane(plane, width: int, height: int) -> np.ndarray:
    # line_size may include padding: view the buffer as rows, then crop. No copy.
    rows = np.frombuffer(plane, dtype="<u2").reshape(height, plane.line_size // 2)
    return rows[:, :width]


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
                    if frame.format.name != EXPECTED_PIX_FMT:
                        raise ValueError(
                            f"format de pixel décodé {frame.format.name}, attendu {EXPECTED_PIX_FMT}"
                        )
                    if frame.pts is not None:
                        if last_pts is not None and step and frame.pts - last_pts != step:
                            self._pts_gaps.append(self._decoded)
                        last_pts = frame.pts
                    w, h = frame.width, frame.height
                    p = frame.planes
                    yield VideoFrame(
                        index=self._decoded,
                        y=_plane(p[0], w, h),
                        cb=_plane(p[1], w // 2, h),
                        cr=_plane(p[2], w // 2, h),
                    )
                    self._decoded += 1

    @property
    def integrity(self) -> IntegrityReport:
        return IntegrityReport(
            frames_expected=self.frames_expected,
            frames_decoded=self._decoded,
            errors=list(self._errors),
            pts_discontinuities=list(self._pts_gaps),
        )


def _pts_step(stream) -> int | None:
    """Expected pts increment between two frames, in stream time base units."""
    rate = stream.guessed_rate or stream.average_rate
    if not rate or not stream.time_base:
        return None
    step = 1 / (rate * stream.time_base)
    return int(step) if step.denominator == 1 else None
