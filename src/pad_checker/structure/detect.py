"""Frame-sequence detectors of the structure step (SPEC §6.2, §6.4, §6.6).

Pure functions over the per-frame measurement columns (NumPy arrays indexed by frame number),
so that they can be tested without video. Every range is ``(first, last)``, inclusive.
"""

from __future__ import annotations

import numpy as np

# A fade has a luma mean that changes monotonically over at least this many frames (SPEC §6.4).
FADE_FRAMES = 3


def runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Ranges of consecutive True values."""
    m = np.asarray(mask, dtype=bool)
    if m.size == 0:
        return []
    edges = np.flatnonzero(np.diff(np.concatenate([[False], m, [False]]).astype(np.int8)))
    return [(int(a), int(b) - 1) for a, b in zip(edges[::2], edges[1::2])]


def leading_run(mask: np.ndarray) -> tuple[int, int] | None:
    if mask.size == 0 or not mask[0]:
        return None
    return runs(mask)[0]


def trailing_run(mask: np.ndarray) -> tuple[int, int] | None:
    if mask.size == 0 or not mask[-1]:
        return None
    return runs(mask)[-1]


def run_ending_at(mask: np.ndarray, last: int) -> tuple[int, int] | None:
    """Run of True values that ends exactly at frame ``last``."""
    if last < 0 or not mask[last]:
        return None
    first = last
    while first > 0 and mask[first - 1]:
        first -= 1
    return first, last


def static(d_mean: np.ndarray, threshold: float) -> np.ndarray:
    """Frames (almost) identical to the previous frame: mean absolute difference below threshold."""
    with np.errstate(invalid="ignore"):
        return np.nan_to_num(d_mean, nan=np.inf) < threshold


def frozen_ranges(is_static: np.ndarray, excluded: np.ndarray, min_frames: int) -> list[tuple[int, int]]:
    """Freezes: the same picture on at least ``min_frames`` frames, outside ``excluded`` frames.

    Frame k static means frames k - 1 and k show the same picture, so a run of static flags
    ``[a, b]`` is a picture held on frames ``a - 1 .. b``.
    """
    held = is_static.copy()
    held[:-1] |= is_static[1:]
    held &= ~excluded
    return [(a, b) for a, b in runs(held) if b - a + 1 >= min_frames]


def duplicates(d_mean: np.ndarray, threshold: float, excluded: np.ndarray) -> list[int]:
    """A single repeated frame in the middle of movement: frame k equals k - 1, while both its
    neighbours differ from their previous frame."""
    with np.errstate(invalid="ignore"):
        moving = np.nan_to_num(d_mean, nan=-np.inf) >= threshold
    same = static(d_mean, threshold)
    k = np.arange(1, d_mean.size - 1)
    hit = same[k] & moving[k - 1] & moving[k + 1] & ~excluded[k]
    return [int(x) for x in k[hit]]


def isolated_black(black: np.ndarray, y_mean: np.ndarray) -> list[int]:
    """Single black frames between non-black frames, except at the end of a fade out or the start
    of a fade in (luma mean strictly decreasing / increasing over ``FADE_FRAMES`` frames)."""
    out: list[int] = []
    n = black.size
    for k in np.flatnonzero(black[1:-1]) + 1:
        if black[k - 1] or black[k + 1]:
            continue
        before = y_mean[max(k - FADE_FRAMES, 0): k + 1]
        after = y_mean[k: k + FADE_FRAMES + 1]
        fade_out = k >= FADE_FRAMES and bool(np.all(np.diff(before) < 0))
        fade_in = k + FADE_FRAMES < n and bool(np.all(np.diff(after) > 0))
        if not (fade_out or fade_in):
            out.append(int(k))
    return out


def flash_ranges(
    d_up_pct: np.ndarray, d_down_pct: np.ndarray, area_pct: float, window: int, max_flashes: int
) -> list[tuple[int, int, int]]:
    """PSE (SPEC §6.6): ranges of frames where some 1 s window holds more than ``max_flashes``
    flashes. Returns (first, last, worst flash count in a window).

    A transition is a frame where more than ``area_pct`` of the picture got brighter (or darker)
    by more than the flash delta (measured in ``d_up_pct`` / ``d_down_pct``). Consecutive
    transitions in the same direction are one transition (a change spread over two frames).
    A flash is a pair of opposite transitions: ``n`` transitions in a window make ``n // 2``
    flashes. ``window`` is one second in frames.
    """
    with np.errstate(invalid="ignore"):
        up = np.nan_to_num(d_up_pct, nan=0.0) >= area_pct
        down = np.nan_to_num(d_down_pct, nan=0.0) >= area_pct
    transitions: list[tuple[int, int]] = []
    for k in np.flatnonzero(up | down):
        for direction, hit in ((1, up[k]), (-1, down[k])):
            if not hit:
                continue
            if transitions and transitions[-1][1] == direction and transitions[-1][0] >= k - 1:
                transitions[-1] = (int(k), direction)  # same change continuing on the next frame
            else:
                transitions.append((int(k), direction))
    frames = np.array([t[0] for t in transitions], dtype=np.int64)
    marked = np.zeros(d_up_pct.size, dtype=bool)
    worst = np.zeros(d_up_pct.size, dtype=np.int64)
    for i, start in enumerate(frames):
        j = int(np.searchsorted(frames, start + window, side="left"))
        flashes = (j - i) // 2
        if flashes > max_flashes:
            last = int(frames[j - 1])
            marked[start: last + 1] = True
            np.maximum(worst[start: last + 1], flashes, out=worst[start: last + 1])
    return [(a, b, int(worst[a: b + 1].max())) for a, b in runs(marked)]
