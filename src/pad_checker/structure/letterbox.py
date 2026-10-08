"""Picture format and black bands (letterbox / pillarbox), SPEC §6.5.

One frame every ``SAMPLE_SECONDS`` of programme (black frames and bars left out) is decoded.
A row (column) is active when its 99.9th percentile reaches ``structure.black.y_max``, the same
criterion as a black frame (``y_p99``), so grain in a black band does not make it active. The
dominant active area over the samples is compared with ``format.letterbox.formats``.
"""

from __future__ import annotations

import math
from collections import Counter

import numpy as np

from pad_checker.rules.profile import Letterbox
from pad_checker.structure.models import LetterboxSample

SAMPLE_SECONDS = 10.0  # SPEC §6.5: "1 image toutes les 10 s"
CHANGE_MIN_SAMPLES = 3  # a different format on fewer consecutive samples is a dark scene, not a change


def _active(counts: np.ndarray, length: int) -> np.ndarray:
    # Nearest-rank 99.9th percentile >= threshold  <=>  enough pixels at or above the threshold.
    return counts >= length - math.ceil(999 * length / 1000) + 1


def active_area(y: np.ndarray, frame: int, black_y_max: int) -> LetterboxSample | None:
    """Active rows and columns of a frame (None: the whole frame is black)."""
    bright = y >= black_y_max
    h, w = y.shape
    rows = np.flatnonzero(_active(bright.sum(axis=1), w))
    cols = np.flatnonzero(_active(bright.sum(axis=0), h))
    if rows.size == 0 or cols.size == 0:
        return None
    return LetterboxSample(frame=frame, top=int(rows[0]), bottom=int(rows[-1]), left=int(cols[0]), right=int(cols[-1]))


def lines(s: LetterboxSample) -> int:
    return s.bottom - s.top + 1


def pixels(s: LetterboxSample) -> int:
    return s.right - s.left + 1


def classify(s: LetterboxSample, spec: Letterbox, tolerance: int) -> str | None:
    for f in spec.formats:
        if abs(lines(s) - f.active_lines) <= tolerance and abs(pixels(s) - f.active_pixels) <= tolerance:
            return f.aspect
    return None


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
    samples: list[LetterboxSample], spec: Letterbox, tolerance: int, reference: LetterboxSample
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
        f = classify(s, spec, tolerance)
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
