"""Per-frame luma / chroma / RGB gamut measurements (SPEC §5.2).

All luma statistics come from one exact histogram of the 10-bit Y plane, so they are integer
and reproducible. Thresholds are converted once from the profile percentages to 10-bit code
values, rounded outward and inclusive (CLAUDE.md decision of 7 October 2026).

RGB gamut: Y'CbCr legal range -> R'G'B' with the inverse matrix of the profile colour space,
in float32, without clipping, expressed in the luma code scale (so that the -5 % / 105 % bounds
become code values like the Y bounds). 4:2:2 chroma is sited on the even luma samples; odd
samples use the mean of the two neighbouring chroma samples (linear interpolation).

Prefilter (profile ``video.prefilter``): horizontal binomial low-pass on Y, Cb and Cr before
every measurement, as recommended by EBU R103 to ignore fleeting overshoots.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable, Iterator
from concurrent.futures import Future, ProcessPoolExecutor
from multiprocessing.shared_memory import SharedMemory
from dataclasses import dataclass
from fractions import Fraction

import numpy as np

from pad_checker.decode.video import VideoFrame
from pad_checker.rules.profile import Profile

# Luma/chroma weights (Kr, Kb) of the supported matrices. BT.2020 comes with HDR (v3).
MATRICES = {"bt709": (0.2126, 0.0722)}

# 10-bit legal chroma: 64..960 around 512 (ITU-R BT.709 §3.4 / BT.1361), a definition, not a threshold.
CHROMA_ZERO = 512
CHROMA_SCALE = 896

FIELDS = (
    "f", "y_min", "y_max", "y_p01", "y_p99", "y_mean",
    "y_below_pct", "y_above_pct", "y_below_legal_pct", "y_above_legal_pct",
    "rgb_out_pct", "cb_min", "cb_max", "cr_min", "cr_max", "sat_max",
)

class MeasureSetupError(ValueError):
    """The profile cannot drive the measurements. The message is user-facing (French)."""


def pct_to_code(pct: float, legal: tuple[int, int], side: str) -> int:
    """Profile percentage -> 10-bit code value, rounded outward (low bound down, high bound up)."""
    lo, hi = legal
    exact = lo + Fraction(str(pct)) / 100 * (hi - lo)
    return math.floor(exact) if side == "low" else math.ceil(exact)


@dataclass(frozen=True)
class VideoLimits:
    y_legal: tuple[int, int]
    y_tolerance: tuple[int, int]
    rgb: tuple[int, int]
    prefilter_taps: int | None
    matrix: str

    @classmethod
    def from_profile(cls, profile: Profile) -> VideoLimits:
        v = profile.video
        legal = (v.y_min_legal, v.y_max_legal)
        matrix = profile.format.color_space
        if matrix not in MATRICES:
            raise MeasureSetupError(
                f"matrice de couleur « {matrix} » non prise en charge pour la conversion RGB "
                f"(prises en charge : {', '.join(MATRICES)})"
            )
        return cls(
            y_legal=legal,
            y_tolerance=(pct_to_code(v.y_tolerance_low_pct, legal, "low"),
                         pct_to_code(v.y_tolerance_high_pct, legal, "high")),
            rgb=(pct_to_code(v.rgb_min_pct, legal, "low"), pct_to_code(v.rgb_max_pct, legal, "high")),
            prefilter_taps=v.prefilter_taps if v.prefilter else None,
            matrix=matrix,
        )

    def rgb_coefficients(self) -> tuple[float, float, float, float]:
        """(Cr->R, Cb->G, Cr->G, Cb->B) gains from centred chroma code values to luma code values."""
        kr, kb = MATRICES[self.matrix]
        kg = 1 - kr - kb
        scale = (self.y_legal[1] - self.y_legal[0]) / CHROMA_SCALE
        return (
            scale * 2 * (1 - kr),
            -scale * 2 * kb * (1 - kb) / kg,
            -scale * 2 * kr * (1 - kr) / kg,
            scale * 2 * (1 - kb),
        )


def hfilter(plane: np.ndarray, taps: int, out: np.ndarray | None = None, pad: np.ndarray | None = None) -> np.ndarray:
    """Horizontal binomial low-pass in integer arithmetic (edges replicated, rounded half up).

    3 taps = [1 2 1] / 4, 5 taps = [1 4 6 4 1] / 16. ``out`` (same shape) and ``pad`` (width +
    taps - 1) are optional preallocated uint16 buffers.
    """
    if taps not in (3, 5):
        raise ValueError(f"prefilter_taps {taps}")
    h, w = plane.shape
    half = taps // 2
    if pad is None:
        pad = np.empty((h, w + 2 * half), dtype=np.uint16)
    if out is None:
        out = np.empty((h, w), dtype=np.uint16)
    pad[:, half:half + w] = plane
    pad[:, :half] = plane[:, :1]
    pad[:, half + w:] = plane[:, -1:]
    if taps == 3:  # (a + 2b + c + 2) >> 2, at most 4094: fits uint16
        np.add(pad[:, 0:w], pad[:, 2:w + 2], out=out)
        out += pad[:, 1:w + 1]
        out += pad[:, 1:w + 1]
        out += 2
        out >>= 2
    else:  # (a + 4b + 6c + 4d + e + 8) >> 4, at most 16376: fits uint16
        np.add(pad[:, 0:w], pad[:, 4:w + 4], out=out)
        for _ in range(4):
            out += pad[:, 1:w + 1]
            out += pad[:, 3:w + 3]
        for _ in range(6):
            out += pad[:, 2:w + 2]
        out += 8
        out >>= 4
    return out


def _below(cum: np.ndarray, code: int) -> int:
    """Number of pixels with a value strictly below ``code``."""
    return 0 if code <= 0 else int(cum[min(code, cum.size) - 1])


def _pct(count: int, total: int) -> float:
    return round(100.0 * count / total, 4)


class _Workspace:
    """Buffers for one strip of rows, reused from strip to strip and frame to frame.

    A frame is processed by strips of ``STRIP_ROWS`` rows so that the temporaries stay in the
    core's cache instead of streaming whole 1080p planes through memory, and are never
    reallocated (a fresh multi-megabyte temporary costs a page fault per 4 KiB).
    """

    def __init__(self, rows: int, w: int, taps: int | None):
        cw = w // 2
        self.key = (rows, w)
        if taps:
            half = taps // 2
            self.y = np.empty((rows, w), np.uint16)
            self.cb = np.empty((rows, cw), np.uint16)
            self.cr = np.empty((rows, cw), np.uint16)
            self.pad_y = np.empty((rows, w + 2 * half), np.uint16)
            self.pad_c = np.empty((rows, cw + 2 * half), np.uint16)
        (self.cbf, self.crf, self.cbo, self.cro, self.tr, self.tg, self.tb,
         self.tmin, self.tmax, self.luma, self.tmp) = (np.empty((rows, cw), np.float32) for _ in range(11))
        self.low = np.empty((rows, cw), np.bool_)
        self.high = np.empty((rows, cw), np.bool_)

    def view(self, rows: int) -> _Workspace:
        """Same buffers cut to the first ``rows`` rows (last strip of a frame)."""
        if rows == self.key[0]:
            return self
        v = object.__new__(_Workspace)
        for name, value in vars(self).items():
            setattr(v, name, value[:rows] if isinstance(value, np.ndarray) else value)
        return v


STRIP_ROWS = 64  # fastest of 8..1080 on a 16-core Zen 3 (16.7 ms per 1080p frame)


class FrameMeter:
    """Measures one frame. Not thread-safe (one workspace): use one meter per process."""

    def __init__(self, limits: VideoLimits, strip_rows: int = STRIP_ROWS):
        self.limits = limits
        self.strip_rows = strip_rows
        self._k = tuple(np.float32(c) for c in limits.rgb_coefficients())
        self._rgb_lo = np.float32(limits.rgb[0])
        self._rgb_hi = np.float32(limits.rgb[1])
        self._ws: _Workspace | None = None

    def _workspace(self, width: int) -> _Workspace:
        if self._ws is None or self._ws.key != (self.strip_rows, width):
            self._ws = _Workspace(self.strip_rows, width, self.limits.prefilter_taps)
        return self._ws

    def measure(self, frame: VideoFrame) -> dict:
        lim = self.limits
        h, w = frame.y.shape
        full = self._workspace(w)
        hist = np.zeros(1024, dtype=np.int64)
        cb_min = cr_min = 1 << 16
        cb_max = cr_max = -1
        sat2 = 0.0
        rgb_out = 0
        for top in range(0, h, self.strip_rows):
            rows = slice(top, top + self.strip_rows)
            y, cb, cr = frame.y[rows], frame.cb[rows], frame.cr[rows]
            ws = full.view(y.shape[0])
            if lim.prefilter_taps:
                y = hfilter(y, lim.prefilter_taps, ws.y, ws.pad_y)
                cb = hfilter(cb, lim.prefilter_taps, ws.cb, ws.pad_c)
                cr = hfilter(cr, lim.prefilter_taps, ws.cr, ws.pad_c)
            hist = _add_histogram(hist, y)
            cb_min, cb_max = min(cb_min, int(cb.min())), max(cb_max, int(cb.max()))
            cr_min, cr_max = min(cr_min, int(cr.min())), max(cr_max, int(cr.max()))
            # Centred chroma in float32 (exact: small integers).
            np.copyto(ws.cbf, cb)
            np.copyto(ws.crf, cr)
            ws.cbf -= CHROMA_ZERO
            ws.crf -= CHROMA_ZERO
            np.multiply(ws.cbf, ws.cbf, out=ws.tmp)
            np.multiply(ws.crf, ws.crf, out=ws.tr)
            ws.tmp += ws.tr
            sat2 = max(sat2, float(ws.tmp.max()))  # exact: at most 2 * 512^2 < 2^24
            rgb_out += self._rgb_out(y, ws)

        n = h * w
        nz = np.flatnonzero(hist)
        cum = np.cumsum(hist)
        # Nearest-rank percentiles: smallest value whose cumulative count reaches p * n.
        p01 = int(np.searchsorted(cum, (n + 999) // 1000))
        p99 = int(np.searchsorted(cum, (999 * n + 999) // 1000))
        total = int(hist @ np.arange(hist.size, dtype=np.int64))
        tol_lo, tol_hi = lim.y_tolerance
        leg_lo, leg_hi = lim.y_legal
        return {
            "f": frame.index,
            "y_min": int(nz[0]),
            "y_max": int(nz[-1]),
            "y_p01": p01,
            "y_p99": p99,
            "y_mean": round(total / n, 3),
            "y_below_pct": _pct(_below(cum, tol_lo), n),
            "y_above_pct": _pct(n - _below(cum, tol_hi + 1), n),
            "y_below_legal_pct": _pct(_below(cum, leg_lo), n),
            "y_above_legal_pct": _pct(n - _below(cum, leg_hi + 1), n),
            "rgb_out_pct": _pct(rgb_out, n),
            "cb_min": cb_min,
            "cb_max": cb_max,
            "cr_min": cr_min,
            "cr_max": cr_max,
            "sat_max": round(math.sqrt(sat2), 2),
        }

    def _rgb_out(self, y: np.ndarray, ws: _Workspace) -> int:
        """Pixels with R, G or B outside the profile bounds. ``ws.cbf`` / ``ws.crf`` hold centred chroma."""
        k_rr, k_gb, k_gr, k_bb = self._k
        cbf, crf, cbo, cro = ws.cbf, ws.crf, ws.cbo, ws.cro
        # Odd luma columns: chroma interpolated between the two co-sited neighbours.
        np.add(cbf[:, :-1], cbf[:, 1:], out=cbo[:, :-1])
        np.add(crf[:, :-1], crf[:, 1:], out=cro[:, :-1])
        cbo[:, :-1] *= np.float32(0.5)
        cro[:, :-1] *= np.float32(0.5)
        cbo[:, -1] = cbf[:, -1]
        cro[:, -1] = crf[:, -1]

        out = 0
        for luma, cbx, crx in ((y[:, 0::2], cbf, crf), (y[:, 1::2], cbo, cro)):
            np.multiply(crx, k_rr, out=ws.tr)
            np.multiply(cbx, k_gb, out=ws.tg)
            np.multiply(crx, k_gr, out=ws.tmp)
            ws.tg += ws.tmp
            np.multiply(cbx, k_bb, out=ws.tb)
            np.minimum(ws.tr, ws.tg, out=ws.tmin)
            np.minimum(ws.tmin, ws.tb, out=ws.tmin)
            np.maximum(ws.tr, ws.tg, out=ws.tmax)
            np.maximum(ws.tmax, ws.tb, out=ws.tmax)
            np.copyto(ws.luma, luma)
            ws.tmin += ws.luma
            ws.tmax += ws.luma
            # Y + min(t) < lo  <=>  one of R, G, B is below the bound (same for the high bound).
            np.less(ws.tmin, self._rgb_lo, out=ws.low)
            np.greater(ws.tmax, self._rgb_hi, out=ws.high)
            ws.low |= ws.high
            out += int(np.count_nonzero(ws.low))
        return out


def _add_histogram(hist: np.ndarray, y: np.ndarray) -> np.ndarray:
    part = np.bincount(y.ravel(), minlength=hist.size)
    if part.size > hist.size:  # values above 1023: not a 10-bit signal, keep them all
        part[: hist.size] += hist
        return part
    hist += part
    return hist


# --- parallel measurement ------------------------------------------------------------------
#
# NumPy work on 1080p frames is made of thousands of small calls that hold the GIL in between:
# threads do not scale. Worker processes do; the decoded planes reach them through a ring of
# frame slots in shared memory (one copy per frame), so the file is still read sequentially by
# a single decoder.

_worker: dict = {}


def _slot_views(buf, slots: int, h: int, w: int) -> list[tuple[np.ndarray, np.ndarray, np.ndarray]]:
    cw = w // 2
    per_slot = h * w + 2 * h * cw
    arr = np.ndarray((slots, per_slot), dtype=np.uint16, buffer=buf)
    return [
        (s[: h * w].reshape(h, w), s[h * w: h * w + h * cw].reshape(h, cw), s[h * w + h * cw:].reshape(h, cw))
        for s in arr
    ]


def _worker_init(shm_name: str, slots: int, h: int, w: int, limits: VideoLimits, strip_rows: int) -> None:
    shm = SharedMemory(name=shm_name)
    _worker.update(shm=shm, views=_slot_views(shm.buf, slots, h, w), meter=FrameMeter(limits, strip_rows))


def _worker_measure(slot: int, index: int) -> dict:
    y, cb, cr = _worker["views"][slot]
    return _worker["meter"].measure(VideoFrame(index=index, y=y, cb=cb, cr=cr))


def measure_frames(
    frames: Iterable[VideoFrame], limits: VideoLimits, workers: int, strip_rows: int = STRIP_ROWS
) -> Iterator[dict]:
    """Measure every frame, yielding the results in frame order.

    ``workers`` <= 1 measures in this process. Otherwise at most ``2 * workers`` frames are in
    flight, so memory stays bounded whatever the film length. Results do not depend on ``workers``.
    """
    if workers <= 1:
        meter = FrameMeter(limits, strip_rows)
        yield from map(meter.measure, frames)
        return

    it = iter(frames)
    first = next(it, None)
    if first is None:
        return
    h, w = first.y.shape
    slots = 2 * workers
    shm = SharedMemory(create=True, size=slots * (h * w + 2 * h * (w // 2)) * 2)
    try:
        views = _slot_views(shm.buf, slots, h, w)
        pool = ProcessPoolExecutor(
            max_workers=workers, initializer=_worker_init, initargs=(shm.name, slots, h, w, limits, strip_rows)
        )
        pending: deque[Future] = deque()
        try:
            for k, frame in enumerate(_chain(first, it)):
                if frame.y.shape != (h, w):
                    raise ValueError(f"image {frame.index} : taille {frame.y.shape} différente de la première {(h, w)}")
                if len(pending) == slots:
                    # The oldest frame is done: its slot (k % slots) can be overwritten.
                    yield pending.popleft().result()
                y, cb, cr = views[k % slots]
                np.copyto(y, frame.y)
                np.copyto(cb, frame.cb)
                np.copyto(cr, frame.cr)
                pending.append(pool.submit(_worker_measure, k % slots, frame.index))
            while pending:
                yield pending.popleft().result()
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
            del views
    finally:
        shm.close()
        shm.unlink()


def _chain(first: VideoFrame, rest: Iterator[VideoFrame]) -> Iterator[VideoFrame]:
    yield first
    yield from rest
