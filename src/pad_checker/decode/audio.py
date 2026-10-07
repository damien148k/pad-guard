"""Audio decoding by track group (SPEC §2.2, §5.3).

A profile track is a channel numbered from 1 across all audio streams. A group (e.g. VO =
tracks 1-2) can therefore take its channels from one stereo stream or from several mono
streams; each stream is demuxed independently and the channels are re-aligned sample by sample.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import av
import numpy as np

from pad_checker.probe.models import AudioTrack

# Integer PCM is normalised to [-1, 1). float32 keeps 24-bit samples exact.
_SCALE = {"s16": 2.0**15, "s16p": 2.0**15, "s32": 2.0**31, "s32p": 2.0**31}


class MissingTrackError(ValueError):
    pass


def resolve_tracks(table: Sequence[AudioTrack], tracks: Sequence[int]) -> list[AudioTrack]:
    by_number = {t.track: t for t in table}
    missing = [t for t in tracks if t not in by_number]
    if missing:
        raise MissingTrackError(
            f"piste(s) {', '.join(map(str, missing))} absente(s) : le fichier contient {len(table)} piste(s)"
        )
    return [by_number[t] for t in tracks]


def _to_float(frame: av.AudioFrame) -> np.ndarray:
    """Decoded frame -> float32 array (channels, samples)."""
    name = frame.format.name
    data = frame.to_ndarray()
    if not frame.format.is_planar:
        data = data.reshape(-1, len(frame.layout.channels)).T
    if name in _SCALE:
        return (data.astype(np.float32) / np.float32(_SCALE[name])).astype(np.float32)
    if name in ("flt", "fltp", "dbl", "dblp"):
        return data.astype(np.float32)
    raise ValueError(f"format d'échantillon audio non pris en charge : {name}")


def _stream_chunks(path: Path, stream_index: int, errors: list[str]) -> Iterator[np.ndarray]:
    with av.open(str(path)) as container:
        stream = next(s for s in container.streams if s.index == stream_index)
        for packet in container.demux(stream):
            try:
                frames = stream.decode(packet)
            except av.FFmpegError as exc:
                errors.append(f"flux {stream_index} : {exc}")
                continue
            for frame in frames:
                yield _to_float(frame)


@dataclass
class AudioGroupDecoder:
    """Yield ``(first_sample, block)`` with ``block`` of shape (len(tracks), n), n <= block_samples."""

    path: Path
    tracks: list[AudioTrack]
    block_samples: int = 4800  # 100 ms at 48 kHz
    errors: list[str] = field(default_factory=list, init=False)
    samples_per_stream: dict[int, int] = field(default_factory=dict, init=False)

    def blocks(self) -> Iterator[tuple[int, np.ndarray]]:
        self.errors.clear()
        streams = sorted({t.stream_index for t in self.tracks})
        sources = {s: _stream_chunks(self.path, s, self.errors) for s in streams}
        pending: dict[int, list[np.ndarray]] = {s: [] for s in streams}
        available = {s: 0 for s in streams}
        done: set[int] = set()
        self.samples_per_stream = {s: 0 for s in streams}
        position = 0

        while True:
            for s in streams:
                while s not in done and available[s] < self.block_samples:
                    chunk = next(sources[s], None)
                    if chunk is None:
                        done.add(s)
                    else:
                        pending[s].append(chunk)
                        available[s] += chunk.shape[1]
                        self.samples_per_stream[s] += chunk.shape[1]
            n = min(min(available.values()), self.block_samples)
            if n == 0:
                break
            taken = {s: _take(pending[s], n) for s in streams}
            for s in streams:
                available[s] -= n
            block = np.stack([taken[t.stream_index][t.channel] for t in self.tracks])
            yield position, block
            position += n


def _take(chunks: list[np.ndarray], n: int) -> np.ndarray:
    """Remove and return the first ``n`` samples of a list of (channels, samples) chunks."""
    out, got = [], 0
    while got < n:
        head = chunks[0]
        need = n - got
        if head.shape[1] <= need:
            out.append(chunks.pop(0))
            got += head.shape[1]
        else:
            out.append(head[:, :need])
            chunks[0] = head[:, need:]
            got = n
    return out[0] if len(out) == 1 else np.concatenate(out, axis=1)
