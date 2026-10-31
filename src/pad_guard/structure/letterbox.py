"""Picture format and black bands (letterbox / pillarbox), SPEC §6.5.

One frame every ``SAMPLE_SECONDS`` of programme (black frames and bars left out) is decoded.
A row (column) is active when its mean luma reaches ``structure.black.y_max``. Not a percentile:
the 8x8 DCT blocks of ProRes and DNxHR ring a few code values above black into the rows of the
band that share a block with the picture (measured: up to 82 on 128 pixels of a row, row mean 65),
so a percentile puts the edge on the block boundary, up to 7 lines off; the mean keeps it on the
exact line (decision of Vincent, 31/10/2026: the blanking must be at the exact line).

The dominant active area over the samples is compared, edge by edge, with each format of
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


def active_area(y: np.ndarray, frame: int, black_y_max: int) -> LetterboxSample | None:
    """Active rows and columns of a frame (None: the whole frame is black)."""
    rows = np.flatnonzero(y.mean(axis=1, dtype=np.float64) >= black_y_max)
    cols = np.flatnonzero(y.mean(axis=0, dtype=np.float64) >= black_y_max)
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
