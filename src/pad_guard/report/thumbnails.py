"""One thumbnail per picture event (``--thumbnails``), SPEC §8 section 6.

The frame shown is the worst frame of the event. For level and gamut events the thumbnail has
two halves: the picture, and the same picture with the pixels counted by the measurement painted
(red: Y above the tolerance, blue: Y below, magenta: R, G or B out of bounds), computed with the
prefilter and thresholds recorded in measurements.json. Painted pixels are max-pooled when the
picture is reduced, so that an isolated out-of-range pixel stays visible.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from pad_guard.decode.video import VideoFrame, read_frames
from pad_guard.labels import VIDEO_TYPES
from pad_guard.measure.models import VideoSettings
from pad_guard.measure.video import CHROMA_ZERO, VideoLimits, out_of_range_masks
from pad_guard.rules.models import Event

SCALE = 3  # 1920x1080 -> 640x360
PAINT = {"y_above": (255, 32, 32), "y_below": (40, 110, 255), "rgb_out": (255, 0, 255)}
MASKS_BY_TYPE = {"white_clip": ("y_above",), "black_crush": ("y_below",), "gamut": ("rgb_out",)}


def limits_from(settings: VideoSettings) -> VideoLimits:
    return VideoLimits(
        y_legal=tuple(settings.y_legal), y_tolerance=tuple(settings.y_tolerance), rgb=tuple(settings.rgb),
        prefilter_taps=settings.prefilter_taps, matrix=settings.matrix, flash_delta_pct=settings.flash_delta_pct,
    )


def to_rgb8(frame: VideoFrame, limits: VideoLimits) -> np.ndarray:
    """Display conversion (legal range BT.709 -> 8-bit sRGB-like), chroma repeated horizontally."""
    k_rr, k_gb, k_gr, k_bb = limits.rgb_coefficients()
    lo, hi = limits.y_legal
    y = frame.y.astype(np.float32)
    cb = np.repeat(frame.cb.astype(np.float32) - CHROMA_ZERO, 2, axis=1)[:, : y.shape[1]]
    cr = np.repeat(frame.cr.astype(np.float32) - CHROMA_ZERO, 2, axis=1)[:, : y.shape[1]]
    rgb = np.stack([y + cr * k_rr, y + cb * k_gb + cr * k_gr, y + cb * k_bb], axis=-1)
    rgb = (rgb - lo) * (255.0 / (hi - lo))
    return np.clip(np.rint(rgb), 0, 255).astype(np.uint8)


def _shrink(rgb: np.ndarray) -> np.ndarray:
    h, w = rgb.shape[0] // SCALE * SCALE, rgb.shape[1] // SCALE * SCALE
    blocks = rgb[:h, :w].reshape(h // SCALE, SCALE, w // SCALE, SCALE, 3).astype(np.uint32)
    return ((blocks.sum(axis=(1, 3)) + SCALE * SCALE // 2) // (SCALE * SCALE)).astype(np.uint8)


def _shrink_mask(mask: np.ndarray) -> np.ndarray:
    h, w = mask.shape[0] // SCALE * SCALE, mask.shape[1] // SCALE * SCALE
    return mask[:h, :w].reshape(h // SCALE, SCALE, w // SCALE, SCALE).any(axis=(1, 3))


def render(frame: VideoFrame, limits: VideoLimits, event_type: str) -> np.ndarray:
    picture = _shrink(to_rgb8(frame, limits))
    names = MASKS_BY_TYPE.get(event_type)
    if not names:
        return picture
    masks = out_of_range_masks(frame, limits)
    painted = (picture // 2).astype(np.uint8)  # dimmed, so that the paint stands out
    for name in names:
        painted[_shrink_mask(masks[name])] = PAINT[name]
    gap = np.full((picture.shape[0], 8, 3), 255, np.uint8)
    return np.concatenate([picture, gap, painted], axis=1)


def file_name(event: Event) -> str:
    return f"evenement_{event.id:03d}.png"


def make(source: Path, stream_index: int, events: list[Event], settings: VideoSettings, out_dir: Path) -> dict[int, str]:
    """Write the thumbnails of the picture events; returns event id -> file name (relative to out_dir)."""
    wanted = [e for e in events if e.type in VIDEO_TYPES and e.scope == "range"]
    if not wanted:
        return {}
    out_dir.mkdir(parents=True, exist_ok=True)
    limits = limits_from(settings)
    by_frame: dict[int, list[Event]] = {}
    for e in wanted:
        by_frame.setdefault(e.worst_frame if e.worst_frame is not None else e.frame_start, []).append(e)
    names: dict[int, str] = {}
    for frame in read_frames(source, by_frame, stream_index):
        for e in by_frame[frame.index]:
            name = file_name(e)
            Image.fromarray(render(frame, limits, e.type)).save(out_dir / name, format="PNG")
            names[e.id] = name
    return names
