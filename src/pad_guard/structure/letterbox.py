"""Picture format and black bands (letterbox / pillarbox), SPEC §6.5.

One frame every ``SAMPLE_SECONDS`` of programme (black frames and bars left out) is decoded.
A row (column) is active when its mean luma reaches ``structure.black.y_max``. Not a percentile:
the 8x8 DCT blocks of ProRes and DNxHR ring a few code values above black into the rows of the
band that share a block with the picture (measured: up to 82 on 128 pixels of a row, row mean 65),
so a percentile puts the edge on the block boundary, up to 7 lines off; the mean keeps it on the
exact line (decision of Vincent, 31/10/2026: the blanking must be at the exact line).

The edges are taken over the whole programme, not from one frame nor from the most frequent area:
a dark scene (night sky, dark ground) loses the edge rows of the picture to the black threshold,
on every one of its frames, and would read as a blanking a few lines off. The samples that fit a
format of the profile (within the tolerance) are grouped by format; when the largest group holds
at least as many samples as the most frequent area, each edge is the outermost position reached
by at least EDGE_MIN_SAMPLES samples of that group: dark samples lie inside it, a flash or a
single picture spilling into the band does not move it. Otherwise (no format of the profile, a
picture that fits none, a few full-frame cards in a 2.39 film), the most frequent area.

Limit: a dark scene that makes up most of the samples and loses more rows than the tolerance on
all of them reads as another format (its dark rows cannot be told from blanking: grain on a bright
edge rings into the band rows up to a row mean of 68, measured on ProRes HQ).

That reference area is compared, edge by edge, with each format of
``format.letterbox.formats`` centred in the frame (Arte §3.2.4 gives lines 87 to 1057 for 2.35
in SMPTE 274M interlaced numbering: rows 132 to 947 of the frame, centred). The deviation is the
largest distance, in lines or pixels, between a measured edge and the expected one.
"""

from __future__ import annotations

from collections import Counter
from fractions import Fraction

import numpy as np

from pad_guard.rules.profile import Letterbox, LetterboxFormat
from pad_guard.structure.models import LetterboxSample

SAMPLE_SECONDS = 10.0  # SPEC §6.5: "1 image toutes les 10 s"
CHANGE_MIN_SAMPLES = 3  # a different format on fewer consecutive samples is a dark scene, not a change
EDGE_MIN_SAMPLES = 3  # an edge is where at least this many samples reach (a flash ringing into the band: fewer)


def active_area(y: np.ndarray, frame: int, black_y_max: int) -> LetterboxSample | None:
    """Active rows and columns of a frame (None: the whole frame is black). The same integer comparison
    as the edges measured on every frame (measure/video.py, ``edges``)."""
    h, w = y.shape
    rows = np.flatnonzero(y.sum(axis=1, dtype=np.uint64) >= np.uint64(black_y_max) * np.uint64(w))
    cols = np.flatnonzero(y.sum(axis=0, dtype=np.uint64) >= np.uint64(black_y_max) * np.uint64(h))
    if rows.size == 0 or cols.size == 0:
        return None
    return LetterboxSample(frame=frame, top=int(rows[0]), bottom=int(rows[-1]), left=int(cols[0]), right=int(cols[-1]))


def lines(s: LetterboxSample) -> int:
    return s.bottom - s.top + 1


def pixels(s: LetterboxSample) -> int:
    return s.right - s.left + 1


def aspect(s: LetterboxSample, sar: Fraction = Fraction(1)) -> float:
    """Picture aspect ratio of the active area (width / height), with the pixel aspect ratio."""
    return round(float(pixels(s) * sar / lines(s)), 2)


def sar_of(text: str | None) -> Fraction:
    """'4:3' -> 4/3; absent or unreadable: square pixels."""
    try:
        num, den = (int(x) for x in (text or "1:1").split(":"))
        return Fraction(num, den) if num > 0 and den > 0 else Fraction(1)
    except ValueError:
        return Fraction(1)


Box = tuple[int, int, int, int]  # top, bottom, left, right: 0-based rows and columns


def expected_boxes(f: LetterboxFormat, width: int, height: int) -> list[Box]:
    """Where format ``f`` lies, centred in a ``width`` x ``height`` frame. An odd number of black lines
    (pixels) cannot be split evenly: both placements are expected."""
    def spans(size: int, active: int) -> list[tuple[int, int]]:
        free = size - active
        starts = sorted({free // 2, (free + 1) // 2})
        return [(a, a + active - 1) for a in starts]
    return [(t, b, l, r) for t, b in spans(height, f.active_lines) for l, r in spans(width, f.active_pixels)]


def deviation(s: LetterboxSample, f: LetterboxFormat, width: int, height: int) -> tuple[int, Box]:
    """Largest distance, in lines or pixels, between an edge of ``s`` and the same edge of ``f``,
    and the expected box it is measured against."""
    return min((max(abs(s.top - t), abs(s.bottom - b), abs(s.left - l), abs(s.right - r)), (t, b, l, r))
               for t, b, l, r in expected_boxes(f, width, height))


def nearest(s: LetterboxSample, spec: Letterbox, width: int, height: int) -> tuple[LetterboxFormat | None, int, Box | None]:
    """Format of the profile closest to ``s`` (first one on a tie), its deviation and expected box."""
    best: tuple[LetterboxFormat | None, int, Box | None] = (None, 0, None)
    for f in spec.formats:
        d, box = deviation(s, f, width, height)
        if best[0] is None or d < best[1]:
            best = (f, d, box)
    return best


def classify(s: LetterboxSample, spec: Letterbox, tolerance: int, width: int, height: int) -> str | None:
    """Format of the profile whose edges are all within ``tolerance`` of those of ``s``."""
    f, d, _ = nearest(s, spec, width, height)
    return f.aspect if f is not None and d <= tolerance else None


def inside(s: LetterboxSample, area: LetterboxSample, tolerance: int) -> bool:
    """``s`` lies within ``area``: a dark scene of the same format leaves part of the picture black."""
    return (s.top >= area.top - tolerance and s.bottom <= area.bottom + tolerance
            and s.left >= area.left - tolerance and s.right <= area.right + tolerance)


def dominant(samples: list[LetterboxSample], tolerance: int) -> tuple[LetterboxSample | None, float]:
    """Most frequent active area (ties: the first one met) and the share of the samples that fit
    within it, in %."""
    if not samples:
        return None, 0.0
    counts = Counter((s.top, s.bottom, s.left, s.right) for s in samples)
    best = max(counts.values())
    key = next(k for k in ((s.top, s.bottom, s.left, s.right) for s in samples) if counts[k] == best)
    first = next(s for s in samples if (s.top, s.bottom, s.left, s.right) == key)
    fitting = sum(inside(s, first, tolerance) for s in samples)
    return first, round(100 * fitting / len(samples), 1)


def reference(samples: list[LetterboxSample], spec: Letterbox, tolerance: int, width: int, height: int
              ) -> tuple[LetterboxSample | None, float]:
    """Active area of the programme (see the module docstring) and the share of the samples that fit
    within it, in %."""
    groups: dict[str, list[LetterboxSample]] = {}
    for s in samples:
        f = classify(s, spec, tolerance, width, height)
        if f is not None:
            groups.setdefault(f, []).append(s)
    mode, share = dominant(samples, tolerance)
    best = max(groups.values(), key=len, default=[])  # ties: the format met first
    key = None if mode is None else (mode.top, mode.bottom, mode.left, mode.right)
    if len(best) < sum((s.top, s.bottom, s.left, s.right) == key for s in samples):
        return mode, share
    k = min(EDGE_MIN_SAMPLES, len(best))
    area = LetterboxSample(
        frame=best[0].frame,
        top=sorted(s.top for s in best)[k - 1], bottom=sorted((s.bottom for s in best), reverse=True)[k - 1],
        left=sorted(s.left for s in best)[k - 1], right=sorted((s.right for s in best), reverse=True)[k - 1])
    fitting = sum(inside(s, area, tolerance) for s in samples)
    return area, round(100 * fitting / len(samples), 1)


def format_changes(
    samples: list[LetterboxSample], spec: Letterbox, tolerance: int, reference: LetterboxSample,
    width: int, height: int,
) -> list[tuple[int, int, str | None, int]]:
    """Runs of at least CHANGE_MIN_SAMPLES consecutive samples whose picture spills over the black
    bands of the dominant area ``reference``: (first frame, last frame, format or None, samples).
    Samples inside the dominant area (dark scenes) are not changes."""
    out: list[tuple[int, int, str | None, int]] = []
    run: list[LetterboxSample] = []
    run_format: str | None = None

    def close() -> None:
        if len(run) >= CHANGE_MIN_SAMPLES:
            out.append((run[0].frame, run[-1].frame, run_format, len(run)))

    for s in samples:
        f = classify(s, spec, tolerance, width, height)
        if inside(s, reference, tolerance):
            close()
            run = []
            continue
        if run and f != run_format:
            close()
            run = []
        run_format = f
        run.append(s)
    close()
    return out


# --- frame by frame (every decoded frame, against the reference of the programme) -------------


def frame_deviations(edges: dict[str, np.ndarray], ref: Box, edge_min: float) -> np.ndarray:
    """Deviation of each frame from the reference ``ref``, in lines or pixels: the largest of the edges
    that count, 0 when none does (NaN edges: a black frame).

    An edge counts when it is measurable (the row or column at it averages at least ``edge_min``, 10-bit
    code values: a dark edge, a fade, credits on black are not) and differs from the reference. Outwards
    (picture in the band) it always counts; inwards only if the opposite edge is measurable and not
    inwards too: a picture smaller on both sides is a fade, a dark scene or credits, not a moved frame.
    """
    top, bottom, left, right = ref
    out_dev = {  # outward positive
        "t": top - edges["a_t"], "b": edges["a_b"] - bottom, "l": left - edges["a_l"], "r": edges["a_r"] - right}
    with np.errstate(invalid="ignore"):
        measurable = {k: edges[f"a_{k}m"] >= edge_min for k in "tblr"}  # NaN: False
    opposite = {"t": "b", "b": "t", "l": "r", "r": "l"}
    worst = np.zeros(edges["a_t"].shape[0], dtype=np.int64)
    for k, d in out_dev.items():
        o = opposite[k]
        with np.errstate(invalid="ignore"):
            counts = measurable[k] & (d != 0) & ((d > 0) | (measurable[o] & (out_dev[o] >= 0)))
        worst = np.where(counts, np.maximum(worst, np.abs(np.nan_to_num(d)).astype(np.int64)), worst)
    return _spread_over_same_box(edges, worst)


def _spread_over_same_box(edges: dict[str, np.ndarray], worst: np.ndarray) -> np.ndarray:
    """A run of consecutive frames with exactly the same four edges is one framing: when some of its frames
    count, all do (a moved shot whose edge row turns dark for a while stays one event, from its first
    frame). A run where no frame counts (a dark scene, a fade) stays at 0."""
    box = np.stack([edges[k] for k in ("a_t", "a_b", "a_l", "a_r")], axis=1)
    n = box.shape[0]
    if n == 0:
        return worst
    with np.errstate(invalid="ignore"):
        same = np.all(box[1:] == box[:-1], axis=1)  # NaN: never the same
    starts = np.concatenate(([0], np.flatnonzero(~same) + 1))
    ends = np.concatenate((starts[1:], [n]))
    out = worst.copy()
    for a, b in zip(starts, ends):
        if b - a > 1:
            m = worst[a:b].max()
            if m:
                out[a:b] = m
    return out


def deviation_runs(dev: np.ndarray, house: int, tolerance: int, min_frames: int
                   ) -> list[tuple[int, int, bool]]:
    """Runs of at least ``min_frames`` consecutive frames that deviate (beyond ``house``): (first, last,
    beyond ``tolerance``). A run is beyond the tolerance when it holds ``min_frames`` consecutive frames
    beyond it; its frames beyond and within are reported together."""
    out = []
    deviating = dev > house
    k, n = 0, dev.shape[0]
    while k < n:
        if not deviating[k]:
            k += 1
            continue
        a = k
        while k < n and deviating[k]:
            k += 1
        b = k - 1
        if b - a + 1 >= min_frames:
            beyond, best = dev[a: b + 1] > tolerance, 0
            run = 0
            for x in beyond:
                run = run + 1 if x else 0
                best = max(best, run)
            out.append((a, b, best >= min_frames))
    return out

