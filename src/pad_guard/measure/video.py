"""Per-frame luma / chroma / RGB gamut measurements (SPEC §5.2).

All luma statistics come from one exact histogram of the Y plane, so they are exact and
reproducible. The values are written as 10-bit code values: a 12-bit file is measured in 12 bits
against the 10-bit thresholds multiplied by 4 exactly, and its values are written divided by 4
(to the quarter); an 8-bit file arrives here converted to 10 bits (decode/video.py). Thresholds are converted once from the profile percentages to 10-bit code
values, rounded outward and inclusive (CLAUDE.md decision of 7 October 2026).

RGB gamut: Y'CbCr legal range -> R'G'B' with the inverse matrix of the profile colour space,
in float32, without clipping, expressed in the luma code scale (so that the -5 % / 105 % bounds
become code values like the Y bounds). 4:2:2 chroma is sited on the even luma samples; odd
samples use the mean of the two neighbouring chroma samples (linear interpolation). 4:2:0 chroma
rows are repeated over the two luma rows they cover; 4:4:4 needs no interpolation.

Prefilter (profile ``video.prefilter``): horizontal binomial low-pass on Y, Cb and Cr before
every level measurement, as recommended by EBU R103 to ignore fleeting overshoots.

Frame differences (structure step: freeze, duplicate frames, PSE) compare the unfiltered Y plane
with the previous frame: ``d_mean`` is the mean absolute difference in 10-bit code values,
``d_up_pct`` / ``d_down_pct`` the share of pixels whose relative luminance rose / fell by more
than ``structure.pse.flash_min_delta_pct``. Relative luminance is the BT.1886 display response
with a zero black level, ``((Y - 64) / 876) ** 2.4`` clipped to [0, 1]; the comparison goes
through two integer lookup tables indexed by the previous code value, so it is exact.

Fields (a file flagged interlaced, decision of Damien of 24 October 2026): the PSE needs the
changes between successive fields, 50 per second in 50i. Two fields of opposite parity sit half a
line apart, so the earlier field is interpolated vertically onto the lines of the later one
(« bob », mean of the two neighbouring lines) before the comparison; ``fu1`` / ``fd1`` compare
the last field of the previous frame with the first field of this one, ``fu2`` / ``fd2`` the
two fields of this frame (share of the field pixels whose luminance rose / fell by more than the
flash delta). The first field is the top one for the flags tt and tb, the bottom one for bb and
bt (FFmpeg writes tb for a top field first ProRes in MOV).

Combing (scan detection, SPEC §12.5): ``comb`` is the mean absolute difference between
neighbouring lines (opposite fields) divided by the mean absolute difference between lines two
apart (same field), on the unfiltered Y plane. Around 0.5-0.8 for progressive pictures, above 1
where the two fields of an interlaced frame show different instants. Integer sums, so exact.
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

from pad_guard import formats
from pad_guard.decode.video import VideoFrame
from pad_guard.rules.profile import Profile

# Luma/chroma weights (Kr, Kb) of the supported matrices (formats.py). BT.2020 comes with HDR.
MATRICES = formats.MATRICES

# 10-bit legal chroma: 64..960 around 512 (ITU-R BT.709 §3.4 / BT.1361), a definition, not a threshold.
CHROMA_ZERO = 512
CHROMA_SCALE = 896

FIELDS = (
    "f", "y_min", "y_max", "y_p01", "y_p99", "y_mean",
    "y_below_pct", "y_above_pct", "y_below_legal_pct", "y_above_legal_pct",
    "rgb_out_pct", "cb_min", "cb_max", "cr_min", "cr_max", "sat_max",
    "d_mean", "d_up_pct", "d_down_pct", "comb",
)
FIELD_FIELDS = ("fu1", "fd1", "fu2", "fd2")  # written only for a file flagged interlaced
LUMINANCE_GAMMA = 2.4  # ITU-R BT.1886 display response (a definition, not a threshold)


def first_field(field_order: str | None) -> str | None:
    """'top' or 'bottom' for an interlaced flag (first letter of the FFmpeg flag), None otherwise."""
    return {"tt": "top", "tb": "top", "bb": "bottom", "bt": "bottom"}.get(field_order or "")


def _bob(field: np.ndarray, onto_bottom: bool, rows: int) -> np.ndarray:
    """``field`` interpolated onto the lines of the other field (``rows`` of them): onto the bottom
    lines, line k lies between field lines k and k + 1; onto the top lines, between k - 1 and k."""
    f = field.astype(np.uint32)
    out = np.empty((rows, field.shape[1]), np.uint32)
    if onto_bottom:
        n = min(rows, f.shape[0] - 1)
        out[:n] = (f[:n] + f[1:n + 1]) >> 1
        out[n:] = f[-1]
    else:
        out[0] = f[0]
        n = min(rows, f.shape[0])
        out[1:n] = (f[: n - 1] + f[1:n]) >> 1
        out[n:] = f[-1]
    return out.astype(np.uint16)


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
    flash_delta_pct: float

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
            flash_delta_pct=profile.structure.pse.flash_min_delta_pct,
        )

    def luminance(self, scale: int = 1) -> np.ndarray:
        """Relative luminance of every code value (float64, 1024 x scale entries, non-decreasing)."""
        lo, hi = self.y_legal
        return np.clip((np.arange(1024 * scale) - lo * scale) / ((hi - lo) * scale), 0.0, 1.0) ** LUMINANCE_GAMMA

    def flash_table(self, scale: int = 1) -> np.ndarray:
        """uint16 table: ``up[p]`` is the first code value whose luminance exceeds that of ``p`` by
        more than the flash delta (1024: none).

        A pixel rose if ``Y >= up[P]`` and fell if ``P >= up[Y]`` (luminance is non-decreasing),
        ``P`` being its value in the previous frame.
        """
        lum = self.luminance(scale)
        return np.searchsorted(lum, lum + self.flash_delta_pct / 100, side="right").astype(np.uint16)

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

    def __init__(self, rows: int, w: int, cw: int, taps: int | None):
        self.key = (rows, w, cw)
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
        self.dmax = np.empty((rows, w), np.uint16)
        self.dmin = np.empty((rows, w), np.uint16)
        self.flag = np.empty((rows, w), np.bool_)

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
        self._k = tuple(np.float32(c) for c in limits.rgb_coefficients())  # same at every scale
        self._ws: _Workspace | None = None
        self._scale: int | None = None
        self._set_scale(1)

    def _set_scale(self, scale: int) -> None:
        """Bounds and tables in the code values of the file (x 4 for a 12-bit file)."""
        if scale == self._scale:
            return
        lim = self.limits
        self._scale = scale
        self._size = 1024 * scale
        self._rgb_lo = np.float32(lim.rgb[0] * scale)
        self._rgb_hi = np.float32(lim.rgb[1] * scale)
        self._chroma_zero = CHROMA_ZERO * scale
        # Indexed by any uint16 value: codes above the range never count as rising or falling.
        self._up = np.full(1 << 16, np.iinfo(np.uint16).max, np.uint16)
        table = lim.flash_table(scale)
        self._up[: self._size] = table
        # Smallest code step that can change the luminance by more than the flash delta: pixels
        # that moved less are skipped (most of them, outside flashes and cuts).
        reachable = np.flatnonzero(table < self._size)
        self._min_step = int((table[reachable] - reachable).min()) if reachable.size else 1 << 16

    def _workspace(self, width: int, chroma_width: int) -> _Workspace:
        if self._ws is None or self._ws.key != (self.strip_rows, width, chroma_width):
            self._ws = _Workspace(self.strip_rows, width, chroma_width, self.limits.prefilter_taps)
        return self._ws

    def _value(self, code: float, digits: int = 2) -> float | int:
        """A code value of the file as a 10-bit code value (unchanged for 8 and 10-bit files)."""
        return code if self._scale == 1 else round(code / self._scale, digits)

    def _field_change(self, before: np.ndarray, after: np.ndarray) -> tuple[float, float]:
        """% of pixels whose luminance rose / fell by more than the flash delta from ``before`` to ``after``."""
        n = after.size
        up = int(np.count_nonzero(after >= self._up[before]))
        return _pct(up, n), _pct(int(np.count_nonzero(before >= self._up[after])), n)

    def fields(self, y: np.ndarray, previous: np.ndarray | None, first: str) -> dict:
        top, bottom = y[0::2], y[1::2]
        top_first = first == "top"
        a, b = (top, bottom) if top_first else (bottom, top)
        fu2, fd2 = self._field_change(_bob(a, top_first, b.shape[0]), b)
        out = {"fu1": None, "fd1": None, "fu2": fu2, "fd2": fd2}
        if previous is not None:
            last = previous[1::2] if top_first else previous[0::2]
            out["fu1"], out["fd1"] = self._field_change(_bob(last, not top_first, a.shape[0]), a)
        return out

    def measure(self, frame: VideoFrame, previous: np.ndarray | None = None, first: str | None = None) -> dict:
        """``previous``: Y plane of the previous frame of the file (None for the first frame);
        ``first``: first field of an interlaced file ('top', 'bottom'), None: no field measures."""
        lim = self.limits
        h, w = frame.y.shape
        if previous is not None and previous.shape != (h, w):
            raise ValueError(f"image {frame.index} : taille {(h, w)} différente de l'image précédente {previous.shape}")
        self._set_scale(frame.scale)
        scale = frame.scale
        full = self._workspace(w, frame.cb.shape[1])
        hist = np.zeros(self._size, dtype=np.int64)
        cb_min = cr_min = 1 << 16
        cb_max = cr_max = -1
        sat2 = 0.0
        rgb_out = 0
        d_sum = d_up = d_down = 0
        across = within = 0
        for top in range(0, h, self.strip_rows):
            rows = slice(top, top + self.strip_rows)
            y = frame.y[rows]
            if frame.vsub == 2:  # 4:2:0: each chroma row covers two luma rows (strips start on even rows)
                n = y.shape[0]
                c_rows = slice(top // 2, top // 2 + (n + 1) // 2)
                cb = np.repeat(frame.cb[c_rows], 2, axis=0)[:n]
                cr = np.repeat(frame.cr[c_rows], 2, axis=0)[:n]
            else:
                cb, cr = frame.cb[rows], frame.cr[rows]
            ws = full.view(y.shape[0])
            if previous is not None:  # before the prefilter: frame differences use the raw plane
                s, u, d = self._diff(y, previous[rows], ws)
                d_sum, d_up, d_down = d_sum + s, d_up + u, d_down + d
            across += self._line_diff(frame.y, top, y.shape[0], 1, ws)
            within += self._line_diff(frame.y, top, y.shape[0], 2, ws)
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
            ws.cbf -= self._chroma_zero
            ws.crf -= self._chroma_zero
            np.multiply(ws.cbf, ws.cbf, out=ws.tmp)
            np.multiply(ws.crf, ws.crf, out=ws.tr)
            ws.tmp += ws.tr
            sat2 = max(sat2, float(ws.tmp.max()))  # exact: at most 2 * 2048^2 < 2^24
            rgb_out += self._rgb_out(y, ws, frame.hsub)

        n = h * w
        nz = np.flatnonzero(hist)
        cum = np.cumsum(hist)
        # Nearest-rank percentiles: smallest value whose cumulative count reaches p * n.
        p01 = int(np.searchsorted(cum, (n + 999) // 1000))
        p99 = int(np.searchsorted(cum, (999 * n + 999) // 1000))
        total = int(hist @ np.arange(hist.size, dtype=np.int64))
        field_values = self.fields(frame.y, previous, first) if first else {}
        tol_lo, tol_hi = (x * scale for x in lim.y_tolerance)
        leg_lo, leg_hi = (x * scale for x in lim.y_legal)
        v = self._value
        return {
            "f": frame.index,
            "y_min": v(int(nz[0])),
            "y_max": v(int(nz[-1])),
            "y_p01": v(p01),
            "y_p99": v(p99),
            "y_mean": round(total / n / scale, 3),
            "y_below_pct": _pct(_below(cum, tol_lo), n),
            "y_above_pct": _pct(n - _below(cum, tol_hi + 1), n),
            "y_below_legal_pct": _pct(_below(cum, leg_lo), n),
            "y_above_legal_pct": _pct(n - _below(cum, leg_hi + 1), n),
            "rgb_out_pct": _pct(rgb_out, n),
            "cb_min": v(cb_min),
            "cb_max": v(cb_max),
            "cr_min": v(cr_min),
            "cr_max": v(cr_max),
            "sat_max": round(math.sqrt(sat2) / scale, 2),
            "d_mean": None if previous is None else round(d_sum / n / scale, 3),
            "d_up_pct": None if previous is None else _pct(d_up, n),
            "d_down_pct": None if previous is None else _pct(d_down, n),
            "comb": None if within == 0 or h < 3 else round((across / (h - 1)) / (within / (h - 2)), 4),
            **field_values,
        }

    @staticmethod
    def _line_diff(plane: np.ndarray, top: int, rows: int, step: int, ws: _Workspace) -> int:
        """Sum of |Y(l) - Y(l + step)| for the lines l of the strip that have a line ``step`` below."""
        n = max(0, min(rows, plane.shape[0] - step - top))
        if n == 0:
            return 0
        a, b = plane[top: top + n], plane[top + step: top + step + n]
        hi, lo = ws.dmax[:n], ws.dmin[:n]
        np.maximum(a, b, out=hi)
        np.minimum(a, b, out=lo)
        hi -= lo
        return int(hi.sum(dtype=np.uint64))

    def _diff(self, y: np.ndarray, prev: np.ndarray, ws: _Workspace) -> tuple[int, int, int]:
        """(sum of |Y - Y_prev|, pixels whose luminance rose, pixels whose luminance fell)."""
        np.maximum(y, prev, out=ws.dmax)
        np.minimum(y, prev, out=ws.dmin)
        ws.dmax -= ws.dmin
        total = int(ws.dmax.sum(dtype=np.uint64))
        np.greater_equal(ws.dmax, self._min_step, out=ws.flag)
        if not ws.flag.any():
            return total, 0, 0
        yc, pc = y[ws.flag], prev[ws.flag]
        # Plain indexing: about three times faster than np.take.
        up = int(np.count_nonzero(yc >= self._up[pc]))
        return total, up, int(np.count_nonzero(pc >= self._up[yc]))

    def _rgb_out(self, y: np.ndarray, ws: _Workspace, hsub: int) -> int:
        """Pixels with R, G or B outside the profile bounds. ``ws.cbf`` / ``ws.crf`` hold centred chroma."""
        k_rr, k_gb, k_gr, k_bb = self._k
        cbf, crf, cbo, cro = ws.cbf, ws.crf, ws.cbo, ws.cro
        if hsub == 1:  # 4:4:4: one chroma sample per luma sample
            passes = ((y, cbf, crf),)
        else:
            # Odd luma columns: chroma interpolated between the two co-sited neighbours.
            np.add(cbf[:, :-1], cbf[:, 1:], out=cbo[:, :-1])
            np.add(crf[:, :-1], crf[:, 1:], out=cro[:, :-1])
            cbo[:, :-1] *= np.float32(0.5)
            cro[:, :-1] *= np.float32(0.5)
            cbo[:, -1] = cbf[:, -1]
            cro[:, -1] = crf[:, -1]
            passes = ((y[:, 0::2], cbf, crf), (y[:, 1::2], cbo, cro))

        out = 0
        for luma, cbx, crx in passes:
            m = luma.shape[1]  # odd width: one odd column less than the even ones
            tr, tg, tb, tmp, tmin, tmax, lum, low, high = (
                a[:, :m] for a in (ws.tr, ws.tg, ws.tb, ws.tmp, ws.tmin, ws.tmax, ws.luma, ws.low, ws.high))
            cbx, crx = cbx[:, :m], crx[:, :m]
            np.multiply(crx, k_rr, out=tr)
            np.multiply(cbx, k_gb, out=tg)
            np.multiply(crx, k_gr, out=tmp)
            tg += tmp
            np.multiply(cbx, k_bb, out=tb)
            np.minimum(tr, tg, out=tmin)
            np.minimum(tmin, tb, out=tmin)
            np.maximum(tr, tg, out=tmax)
            np.maximum(tmax, tb, out=tmax)
            np.copyto(lum, luma)
            tmin += lum
            tmax += lum
            # Y + min(t) < lo  <=>  one of R, G, B is below the bound (same for the high bound).
            np.less(tmin, self._rgb_lo, out=low)
            np.greater(tmax, self._rgb_hi, out=high)
            low |= high
            out += int(np.count_nonzero(low))
        return out


def out_of_range_masks(frame: VideoFrame, limits: VideoLimits) -> dict[str, np.ndarray]:
    """Full-resolution masks of the pixels counted by ``y_above_pct``, ``y_below_pct`` and
    ``rgb_out_pct`` (same prefilter, bounds and chroma interpolation as :class:`FrameMeter`).
    For thumbnails: a few frames, not the measurement path."""
    s = frame.scale
    y, cb, cr = frame.y, frame.cb, frame.cr
    h, w = y.shape
    if frame.vsub == 2:
        cb, cr = np.repeat(cb, 2, axis=0)[:h], np.repeat(cr, 2, axis=0)[:h]
    if limits.prefilter_taps:
        y, cb, cr = (hfilter(p, limits.prefilter_taps) for p in (y, cb, cr))
    k_rr, k_gb, k_gr, k_bb = (np.float32(c) for c in limits.rgb_coefficients())
    cbf = cb.astype(np.float32) - CHROMA_ZERO * s
    crf = cr.astype(np.float32) - CHROMA_ZERO * s
    if frame.hsub == 1:
        cbx, crx = cbf, crf
    else:
        cbx = np.empty((h, w), np.float32)
        crx = np.empty((h, w), np.float32)
        cbx[:, 0::2], crx[:, 0::2] = cbf[:, : (w + 1) // 2], crf[:, : (w + 1) // 2]
        cbx[:, 1:-1:2] = (cbf[:, :-1] + cbf[:, 1:])[:, : (w - 1) // 2] * np.float32(0.5)
        crx[:, 1:-1:2] = (crf[:, :-1] + crf[:, 1:])[:, : (w - 1) // 2] * np.float32(0.5)
        if w % 2 == 0:
            cbx[:, -1], crx[:, -1] = cbf[:, -1], crf[:, -1]
    luma = y.astype(np.float32)
    r = luma + crx * k_rr
    g = luma + cbx * k_gb + crx * k_gr
    b = luma + cbx * k_bb
    lo, hi = np.float32(limits.rgb[0] * s), np.float32(limits.rgb[1] * s)
    rgb = (np.minimum(np.minimum(r, g), b) < lo) | (np.maximum(np.maximum(r, g), b) > hi)
    return {"y_above": y > limits.y_tolerance[1] * s, "y_below": y < limits.y_tolerance[0] * s, "rgb_out": rgb}


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


def _slot_views(buf, slots: int, h: int, w: int, ch: int, cw: int) -> list[tuple[np.ndarray, np.ndarray, np.ndarray]]:
    per_slot = h * w + 2 * ch * cw
    arr = np.ndarray((slots, per_slot), dtype=np.uint16, buffer=buf)
    return [
        (s[: h * w].reshape(h, w), s[h * w: h * w + ch * cw].reshape(ch, cw), s[h * w + ch * cw:].reshape(ch, cw))
        for s in arr
    ]


def _worker_init(shm_name: str, slots: int, shapes: tuple[int, int, int, int], layout: tuple[int, int, int],
                 limits: VideoLimits, strip_rows: int, first: str | None) -> None:
    shm = SharedMemory(name=shm_name)
    _worker.update(shm=shm, views=_slot_views(shm.buf, slots, *shapes), layout=layout, first=first,
                   meter=FrameMeter(limits, strip_rows))


def _worker_measure(slot: int, index: int, previous_slot: int | None) -> dict:
    views = _worker["views"]
    y, cb, cr = views[slot]
    scale, hsub, vsub = _worker["layout"]
    previous = None if previous_slot is None else views[previous_slot][0]
    frame = VideoFrame(index=index, y=y, cb=cb, cr=cr, scale=scale, hsub=hsub, vsub=vsub)
    return _worker["meter"].measure(frame, previous, _worker["first"])


def measure_frames(
    frames: Iterable[VideoFrame], limits: VideoLimits, workers: int, strip_rows: int = STRIP_ROWS,
    first_field: str | None = None,
) -> Iterator[dict]:
    """Measure every frame, yielding the results in frame order.

    ``workers`` <= 1 measures in this process. Otherwise fewer than ``2 * workers`` frames are in
    flight, so memory stays bounded whatever the film length. Results do not depend on ``workers``.
    Each frame is also compared with the frame before it (frame differences).
    """
    if workers <= 1:
        meter = FrameMeter(limits, strip_rows)
        previous: VideoFrame | None = None
        for frame in frames:
            yield meter.measure(frame, None if previous is None else previous.y, first_field)
            previous = frame
        return

    it = iter(frames)
    first = next(it, None)
    if first is None:
        return
    h, w = first.y.shape
    ch, cw = first.cb.shape
    layout = (first.scale, first.hsub, first.vsub)
    slots = max(2 * workers, 3)
    shm = SharedMemory(create=True, size=slots * (h * w + 2 * ch * cw) * 2)
    try:
        views = _slot_views(shm.buf, slots, h, w, ch, cw)
        pool = ProcessPoolExecutor(
            max_workers=workers, initializer=_worker_init,
            initargs=(shm.name, slots, (h, w, ch, cw), layout, limits, strip_rows, first_field),
        )
        pending: deque[Future] = deque()
        try:
            for k, frame in enumerate(_chain(first, it)):
                if frame.y.shape != (h, w) or frame.cb.shape != (ch, cw) or (frame.scale, frame.hsub, frame.vsub) != layout:
                    raise ValueError(f"image {frame.index} : taille ou format différent de la première image")
                if len(pending) == slots - 1:
                    # Slot k % slots holds frame k - slots, the previous frame of frame k - slots + 1
                    # (the oldest in flight): it can be overwritten once that frame is done.
                    yield pending.popleft().result()
                y, cb, cr = views[k % slots]
                np.copyto(y, frame.y)
                np.copyto(cb, frame.cb)
                np.copyto(cr, frame.cr)
                previous_slot = (k - 1) % slots if k else None
                pending.append(pool.submit(_worker_measure, k % slots, frame.index, previous_slot))
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
