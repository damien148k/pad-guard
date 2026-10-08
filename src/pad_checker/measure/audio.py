"""Audio measurements by 100 ms block and over the programme range (SPEC §5.3).

Two sources, one pass each over the audio of the file:

* FFmpeg ``ebur128`` for loudness (momentary, short-term, integrated, LRA): it is the reference
  implementation (SPEC §5.3), and its LUFS values are given to 0.001 LU. One FFmpeg process
  handles every group; each group is measured twice, over the whole file (100 ms blocks for the
  report and the structure step) and over the programme range (integrated loudness and LRA,
  head and tail excluded).
* NumPy, on the samples decoded by PyAV, for everything that needs sample accuracy: true peak
  (ITU-R BS.1770-4 Annex 2 four-times oversampling, per block, so that a peak gets a timecode;
  FFmpeg only reports a running maximum to three linear decimals), sample peak, RMS,
  full-scale runs, and, for 2-track groups, correlation and difference L - R.

Blocks are aligned on the first sample of the file: block ``k`` covers samples
``[k * block, (k + 1) * block)``. ``m`` is the momentary loudness of the 400 ms window ending at
the end of block ``k`` (``None`` for the first three blocks), ``s`` the short-term loudness of
the 3 s window ending there (``None`` for the first 29 blocks).
"""

from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from pad_checker.decode.audio import AudioGroupDecoder
from pad_checker.measure.models import GroupLoudness, ProgramRange, TrackLevels
from pad_checker.probe.models import AudioStreamInfo, AudioTrack
from pad_checker.rules.profile import AudioGroup

# ITU-R BS.1770-4 Annex 2: 48-tap interpolation filter for 4x oversampling, as 4 phases of 12.
TRUE_PEAK_FIR = np.array([
    [0.0017089843750, 0.0109863281250, -0.0196533203125, 0.0332031250000, -0.0594482421875, 0.1373291015625,
     0.9721679687500, -0.1022949218750, 0.0476074218750, -0.0266113281250, 0.0148925781250, -0.0083007812500],
    [-0.0291748046875, 0.0292968750000, -0.0517578125000, 0.0891113281250, -0.1665039062500, 0.4650878906250,
     0.7797851562500, -0.2003173828125, 0.1015625000000, -0.0582275390625, 0.0330810546875, -0.0189208984375],
    [-0.0189208984375, 0.0330810546875, -0.0582275390625, 0.1015625000000, -0.2003173828125, 0.7797851562500,
     0.4650878906250, -0.1665039062500, 0.0891113281250, -0.0517578125000, 0.0292968750000, -0.0291748046875],
    [-0.0083007812500, 0.0148925781250, -0.0266113281250, 0.0476074218750, -0.1022949218750, 0.9721679687500,
     0.1373291015625, -0.0594482421875, 0.0332031250000, -0.0196533203125, 0.0109863281250, 0.0017089843750],
])
_TAPS = TRUE_PEAK_FIR.shape[1]
# Filter output i is centred between input samples i - 6 and i - 5 (largest taps at 5 and 6):
# it is credited to sample i - 6, which needs 6 samples of look-ahead.
_DELAY = 6

BLOCK_FIELDS = ("g", "t", "m", "s", "tp", "peak", "rms", "clip", "corr", "diff")

_FFMPEG_LAYOUT = {"mono": "mono", "dual_mono": "stereo", "stereo": "stereo", "5.1": "5.1"}
_NO_GATED_BLOCK = -70.0  # ebur128 reports this integrated value when no block passes the gate


class AudioMeasureError(Exception):
    """The audio cannot be measured. The message is user-facing (French)."""


def db20(value: float) -> float | None:
    return None if value <= 0 else round(20 * math.log10(value), 3)


def db10(value: float) -> float | None:
    return None if value <= 0 else round(10 * math.log10(value), 3)


def full_scale(bit_depth: int | None) -> float:
    """Smallest normalised magnitude that counts as full scale (largest positive integer code)."""
    bits = bit_depth or 24
    return (2 ** (bits - 1) - 1) / 2 ** (bits - 1)


# --- NumPy pass -----------------------------------------------------------------------------


@dataclass
class _Totals:
    """Programme-range accumulators of one track."""

    peak: float = 0.0
    true_peak: float = 0.0
    sumsq: float = 0.0
    count: int = 0
    full_scale: int = 0


@dataclass
class _PairTotals:
    sum_lr: float = 0.0
    diff_peak: float = 0.0


@dataclass
class LevelPass:
    """Per-block levels of every track, and programme-range totals."""

    path: Path
    tracks: list[AudioTrack]
    bit_depths: list[int | None]
    pairs: list[tuple[int, int]]  # positions in ``tracks`` of the 2-track groups
    block: int
    program: tuple[int, int]
    blocks: dict[str, list[np.ndarray]] = field(default_factory=dict, init=False)
    totals: list[_Totals] = field(default_factory=list, init=False)
    pair_totals: list[_PairTotals] = field(default_factory=list, init=False)
    errors: list[str] = field(default_factory=list, init=False)

    def run(self) -> None:
        n_tr = len(self.tracks)
        self.totals = [_Totals() for _ in range(n_tr)]
        self.pair_totals = [_PairTotals() for _ in self.pairs]
        thresholds = np.array([full_scale(b) for b in self.bit_depths])[:, None]
        names = ("tp", "peak", "sumsq", "count", "clip", "sum_lr", "diff")
        out: dict[str, list[np.ndarray]] = {k: [] for k in names}
        history = np.zeros((n_tr, _TAPS - 1))
        run_carry = np.zeros(n_tr, dtype=np.int64)  # full-scale run still open at the end of the last chunk
        p0, p1 = self.program

        # 1 s chunks (a whole number of blocks): few NumPy calls, small arrays.
        decoder = AudioGroupDecoder(self.path, self.tracks, block_samples=10 * self.block)
        for start, chunk, ahead in _lookahead(decoder.blocks(), _DELAY):
            x = chunk.astype(np.float64)
            n = x.shape[1]
            edges = np.arange(0, n, self.block)
            ax = np.abs(x)

            # True peak = max(|oversampled|, |samples|): the interpolation filter alone can read a
            # little under a full-scale sample. ``history`` carries the 11 previous samples (zeros
            # before the file), ``ahead`` the 6 next ones (zeros after the file).
            ext = np.concatenate([history, x, ahead.astype(np.float64)], axis=1)
            history = ext[:, n:n + _TAPS - 1]
            tp = ax.copy()
            for c in range(n_tr):
                for phase in TRUE_PEAK_FIR:
                    interp = np.convolve(ext[c], phase, mode="valid")[_DELAY:]
                    np.maximum(tp[c], np.abs(interp), out=tp[c])

            full = ax >= thresholds
            clip, run_carry, ended = _clip_runs(full, edges, run_carry)
            if out["clip"]:  # runs that ended exactly at the previous chunk boundary
                np.maximum(out["clip"][-1][:, -1], ended, out=out["clip"][-1][:, -1])

            out["tp"].append(np.maximum.reduceat(tp, edges, axis=1))
            out["peak"].append(np.maximum.reduceat(ax, edges, axis=1))
            out["sumsq"].append(np.add.reduceat(x * x, edges, axis=1))
            out["count"].append(np.diff(np.append(edges, n)))
            out["clip"].append(clip)
            lr = np.array([x[a] * x[b] for a, b in self.pairs]).reshape(len(self.pairs), n)
            dd = np.array([np.abs(x[a] - x[b]) for a, b in self.pairs]).reshape(len(self.pairs), n)
            out["sum_lr"].append(np.add.reduceat(lr, edges, axis=1) if self.pairs else np.zeros((0, len(edges))))
            out["diff"].append(np.maximum.reduceat(dd, edges, axis=1) if self.pairs else np.zeros((0, len(edges))))

            # Programme-range totals, sample exact.
            a, b = max(p0 - start, 0), min(p1 - start, n)
            if a < b:
                for i, t in enumerate(self.totals):
                    t.peak = max(t.peak, float(ax[i, a:b].max()))
                    t.true_peak = max(t.true_peak, float(tp[i, a:b].max()))
                    t.sumsq += float(np.dot(x[i, a:b], x[i, a:b]))
                    t.count += b - a
                    t.full_scale += int(full[i, a:b].sum())
                for j, pt in enumerate(self.pair_totals):
                    pt.sum_lr += float(lr[j, a:b].sum())
                    pt.diff_peak = max(pt.diff_peak, float(dd[j, a:b].max()))

        self.errors = list(decoder.errors)
        if out["clip"]:  # a run still open at the end of the file belongs to the last block
            np.maximum(out["clip"][-1][:, -1], run_carry, out=out["clip"][-1][:, -1])
        self.blocks = {k: (np.concatenate(v, axis=-1) if v else np.zeros((0,))) for k, v in out.items()}


def _lookahead(
    chunks: Iterator[tuple[int, np.ndarray]], k: int
) -> Iterator[tuple[int, np.ndarray, np.ndarray]]:
    """(start, chunk, first ``k`` samples of the next chunk, zero-padded at the end of the file)."""
    current = next(chunks, None)
    while current is not None:
        following = next(chunks, None)
        start, x = current
        ahead = np.zeros((x.shape[0], k), dtype=x.dtype)
        if following is not None:
            head = following[1][:, :k]
            ahead[:, : head.shape[1]] = head
        yield start, x, ahead
        current = following


def _clip_runs(full: np.ndarray, edges: np.ndarray, carry: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Longest run of consecutive full-scale samples ending in each block of a chunk.

    A run crossing block or chunk boundaries is counted whole, in the block where it ends.
    ``carry`` holds the length of the runs still open at the end of the previous chunk. Returns
    (per-block maxima, runs still open at the end of this chunk, carried runs that ended exactly
    at the previous chunk boundary).
    """
    n_tr, n = full.shape
    clip = np.zeros((n_tr, len(edges)), dtype=np.int64)
    ended = np.zeros(n_tr, dtype=np.int64)
    carry = carry.copy()
    for i in range(n_tr):
        idx = np.flatnonzero(full[i])
        if idx.size == 0 or idx[0] != 0:
            ended[i] = carry[i]
            carry[i] = 0
        if idx.size == 0:
            continue
        breaks = np.flatnonzero(np.diff(idx) != 1)
        starts = np.concatenate([[idx[0]], idx[breaks + 1]])
        ends = np.concatenate([idx[breaks], [idx[-1]]])  # inclusive
        lengths = ends - starts + 1
        lengths[0] += carry[i]  # zero unless the first run continues the open one
        open_run = ends[-1] == n - 1
        last = len(starts) - 1 if open_run else len(starts)
        blocks = np.searchsorted(edges, ends[:last], side="right") - 1
        np.maximum.at(clip[i], blocks, lengths[:last])
        carry[i] = lengths[-1] if open_run else 0
    return clip, carry, ended


# --- FFmpeg loudness ------------------------------------------------------------------------


@dataclass
class LoudnessCurve:
    m: list[float | None]
    s: list[float | None]
    integrated: float | None = None
    lra: float | None = None


def _parse_metadata(path: Path) -> list[dict[str, float]]:
    frames: list[dict[str, float]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("frame:"):
            frames.append({})
        elif "=" in line and frames:
            key, _, value = line.partition("=")
            try:
                frames[-1][key.removeprefix("lavfi.r128.")] = float(value)
            except ValueError:
                pass
    return frames


def _curve(frames: list[dict[str, float]]) -> LoudnessCurve:
    # Windows not yet full (first 400 ms, first 3 s) are not measurements.
    m = [f.get("M") if k >= 3 else None for k, f in enumerate(frames)]
    s = [f.get("S") if k >= 29 else None for k, f in enumerate(frames)]
    curve = LoudnessCurve(m=m, s=s)
    if frames:
        last = frames[-1]
        integrated = last.get("I")
        curve.integrated = None if integrated is None or integrated <= _NO_GATED_BLOCK else integrated
        curve.lra = last.get("LRA") if curve.integrated is not None else None
    return curve


def ffmpeg_loudness(
    path: Path,
    streams: Sequence[AudioStreamInfo],
    groups: Sequence[AudioGroup],
    block: int,
    program: tuple[int, int],
) -> tuple[dict[str, LoudnessCurve], dict[str, LoudnessCurve]]:
    """(whole file, programme range) loudness curves of each group, in one FFmpeg run."""
    exe = shutil.which("ffmpeg")
    if exe is None:
        raise AudioMeasureError("ffmpeg introuvable : installer FFmpeg 6+ et l'ajouter au PATH.")
    # All audio streams merged in order: channel c of the merged stream is track c + 1.
    inputs = "".join(f"[0:{s.stream_index}]" for s in streams)
    graph = [f"{inputs}amerge=inputs={len(streams)},asplit={2 * len(groups)}" if len(streams) > 1
             else f"{inputs}asplit={2 * len(groups)}"]
    graph[0] += "".join(f"[s{i}]" for i in range(2 * len(groups)))
    for g, group in enumerate(groups):
        pan = f"pan={_FFMPEG_LAYOUT[group.layout]}|" + "|".join(f"c{i}=c{t - 1}" for i, t in enumerate(group.tracks))
        meter = f"asetnsamples=n={block}:p=0,ebur128=metadata=1"
        graph.append(f"[s{2 * g}]{pan},{meter},ametadata=mode=print:file=full{g}.txt[o{2 * g}]")
        graph.append(
            f"[s{2 * g + 1}]{pan},atrim=start_sample={program[0]}:end_sample={program[1]},"
            f"{meter},ametadata=mode=print:file=prog{g}.txt[o{2 * g + 1}]"
        )
    maps = [arg for i in range(2 * len(groups)) for arg in ("-map", f"[o{i}]")]
    with tempfile.TemporaryDirectory(prefix="pad-checker-") as tmp:
        # Relative metadata file names: no drive letter to escape in the filter graph.
        proc = subprocess.run(
            [exe, "-v", "error", "-nostdin", "-i", str(path.resolve()), "-filter_complex", ";".join(graph),
             *maps, "-f", "null", "-"],
            cwd=tmp, capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if proc.returncode != 0:
            detail = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else f"code {proc.returncode}"
            raise AudioMeasureError(f"mesure de loudness par FFmpeg impossible : {detail}")
        full = {g.name: _curve(_parse_metadata(Path(tmp) / f"full{i}.txt")) for i, g in enumerate(groups)}
        prog = {g.name: _curve(_parse_metadata(Path(tmp) / f"prog{i}.txt")) for i, g in enumerate(groups)}
    return full, prog


# --- assembly -------------------------------------------------------------------------------


def _max_or_none(values: Sequence[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return max(present) if present else None


def track_levels(levels: LevelPass) -> list[TrackLevels]:
    return [
        TrackLevels(
            track=t.track,
            stream_index=t.stream_index,
            channel=t.channel,
            peak_dbfs=db20(tot.peak),
            true_peak_dbtp=db20(tot.true_peak),
            rms_dbfs=db10(tot.sumsq / tot.count) if tot.count else None,
            full_scale_samples=tot.full_scale,
        )
        for t, tot in zip(levels.tracks, levels.totals)
    ]


def group_loudness(
    group: AudioGroup, levels: LevelPass, positions: list[int], pair: int | None, prog: LoudnessCurve
) -> GroupLoudness:
    totals = [levels.totals[p] for p in positions]
    corr = diff = None
    if pair is not None:
        a, b = totals
        pt = levels.pair_totals[pair]
        corr = round(pt.sum_lr / math.sqrt(a.sumsq * b.sumsq), 4) if a.sumsq > 0 and b.sumsq > 0 else None
        diff = db20(pt.diff_peak)
    return GroupLoudness(
        group=group,
        integrated_lufs=prog.integrated,
        lra_lu=prog.lra,
        momentary_max_lufs=_max_or_none(prog.m),
        short_term_max_lufs=_max_or_none(prog.s),
        true_peak_dbtp=db20(max((t.true_peak for t in totals), default=0.0)),
        sample_peak_dbfs=db20(max((t.peak for t in totals), default=0.0)),
        correlation=corr,
        difference_peak_dbfs=diff,
    )


def block_lines(
    group: AudioGroup,
    levels: LevelPass,
    positions: list[int],
    pair: int | None,
    curve: LoudnessCurve,
    sample_rate: int,
) -> Iterator[dict]:
    """JSON Lines records of one group, one per block."""
    b = levels.blocks
    count = b["count"]
    for k in range(count.shape[0]):
        n = int(count[k])
        rec = {
            "g": group.name,
            "t": round(k * levels.block / sample_rate, 3),
            "m": curve.m[k] if k < len(curve.m) else None,
            "s": curve.s[k] if k < len(curve.s) else None,
            "tp": [db20(float(b["tp"][p, k])) for p in positions],
            "peak": [db20(float(b["peak"][p, k])) for p in positions],
            "rms": [db10(float(b["sumsq"][p, k]) / n) for p in positions],
            "clip": [int(b["clip"][p, k]) for p in positions],
            "corr": None,
            "diff": None,
        }
        if pair is not None:
            sl, sr = (float(b["sumsq"][p, k]) for p in positions)
            if sl > 0 and sr > 0:
                rec["corr"] = round(float(b["sum_lr"][pair, k]) / math.sqrt(sl * sr), 4)
            rec["diff"] = db20(float(b["diff"][pair, k]))
        yield rec
