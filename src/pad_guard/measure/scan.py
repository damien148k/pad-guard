"""Scan detection from the per-frame combing indicator (SPEC §12.5).

The container flag (``field_order``) says what the file claims; the pictures say what it is. A
frame counts only if it moves (``d_mean`` at least ``motion_min``): a still interlaced frame
shows no combing. Among the moving frames, the share of combed ones (``comb`` at least
``comb_ratio_min``) gives the scan; too few moving frames, or a share between the two limits,
leaves it undetermined.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from pad_guard.measure.models import ScanSummary
from pad_guard.probe.models import VideoInfo
from pad_guard.rules.profile import ScanDetection


def _number(x: float | None) -> float | None:
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else x


def detect(video: VideoInfo, comb: Sequence[float | None], d_mean: Sequence[float | None],
           settings: ScanDetection) -> ScanSummary:
    moving = combed = 0
    for c, d in zip(comb, d_mean):
        c, d = _number(c), _number(d)
        if c is None or d is None or d < settings.motion_min:
            continue
        moving += 1
        combed += c >= settings.comb_ratio_min
    pct = None if moving == 0 else round(100 * combed / moving, 2)
    if moving < settings.min_moving_frames or pct is None:
        detected = "undetermined"
    elif pct >= settings.interlaced_min_pct:
        detected = "interlaced"
    elif pct <= settings.progressive_max_pct:
        detected = "progressive"
    else:
        detected = "undetermined"
    agrees = None if detected == "undetermined" or video.scan_flag == "unknown" else detected == video.scan_flag
    return ScanSummary(field_order=video.field_order, flag=video.scan_flag, detected=detected,
                       moving_frames=moving, combed_frames=combed, combed_pct=pct, agrees=agrees,
                       settings=settings)


SCAN_LABELS = {"progressive": "progressif", "interlaced": "entrelacé", "undetermined": "indéterminé",
               "unknown": "inconnu"}


def warning(scan: ScanSummary) -> str | None:
    """French warning when the flag and the pictures disagree (None when they agree or cannot be compared)."""
    if scan.agrees is not False:
        return None
    return (f"le drapeau de balayage du fichier ({scan.field_order}, {SCAN_LABELS[scan.flag]}) ne concorde pas "
            f"avec les images ({SCAN_LABELS[scan.detected]} : {scan.combed_frames} image(s) peignée(s) sur "
            f"{scan.moving_frames} en mouvement) : vérifier à l'image")
