"""Master compared with the delivery format of the profile (CLAUDE.md, « Format de livraison »).

The master analysed is Lumiris' file; the broadcaster receives a file made from it. When their
scan or frame rate differ, a conversion is needed before delivery: the report says so (section
« Livraison ») with an ``info`` event, ``delivery_conversion_required``. It is not a
non-conformity of the master. The delivery codec is recalled but never compared: the master
(ProRes, DNxHR) is always transcoded by the facility.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from pad_guard.measure.models import Measurements
from pad_guard.probe.models import ProbeResult
from pad_guard.rules.profile import Profile, require

SCAN_LABELS = {
    "progressive": "progressif",
    "interlaced": "entrelacé",
    "interlaced_tff": "entrelacé, trame haute en premier",
    "interlaced_bff": "entrelacé, trame basse en premier",
    "psf": "progressif segmenté (PsF)",
    "unknown": "balayage inconnu",
}


def _rate(fps: Fraction) -> str:
    return f"{float(fps):.3f}".rstrip("0").rstrip(".").replace(".", ",")


def format_label(fps: Fraction, scan: str) -> str:
    """'25p', '50i' (25 frames, 50 fields per second), '25PsF'."""
    if scan.startswith("interlaced"):
        return f"{_rate(2 * fps)}i"
    if scan == "psf":
        return f"{_rate(fps)}PsF"
    if scan == "progressive":
        return f"{_rate(fps)}p"
    return f"{_rate(fps)} i/s"


@dataclass
class Comparison:
    master: str  # "25p progressif"
    master_scan: str  # progressive | interlaced | unknown
    scan_from: str  # French: how the master scan was found
    delivery: str | None  # "50p ou 25p progressif"; None: the profile has no format.delivery
    codec: str | None
    differences: list[str] = field(default_factory=list)  # French, empty: no conversion needed


def master_scan(probe: ProbeResult, m: Measurements) -> tuple[str, str]:
    """Scan of the master: what the pictures show, else what the container declares."""
    if m.scan.detected in ("progressive", "interlaced"):
        return m.scan.detected, "détecté sur les images"
    if probe.video.scan_flag != "unknown":
        return probe.video.scan_flag, f"d'après le drapeau du fichier ({probe.video.field_order}), détection indéterminée"
    return "unknown", "drapeau absent et détection indéterminée"


def compare(probe: ProbeResult, m: Measurements, profile: Profile) -> Comparison:
    fps = Fraction(probe.video.r_frame_rate)
    scan, how = master_scan(probe, m)
    master = f"{format_label(fps, scan)} {SCAN_LABELS[scan]}".strip()
    d = profile.format.delivery
    if d is None:
        return Comparison(master=master, master_scan=scan, scan_from=how, delivery=None, codec=None)
    wanted_scan = require(profile, "format.delivery.scan", "la comparaison au format de livraison")
    rates = [Fraction(r) for r in require(profile, "format.delivery.fps", "la comparaison au format de livraison")]
    delivery = f"{' ou '.join(format_label(r, wanted_scan) for r in rates)} {SCAN_LABELS[wanted_scan]}"
    differences = []
    wanted_class = "interlaced" if wanted_scan.startswith("interlaced") else "progressive"
    if scan != "unknown" and scan != wanted_class:
        differences.append(f"balayage {SCAN_LABELS[scan]} → {SCAN_LABELS[wanted_scan]}")
    if fps not in rates:
        differences.append(f"cadence {format_label(fps, scan)} → {' ou '.join(format_label(r, wanted_scan) for r in rates)}")
    return Comparison(master=master, master_scan=scan, scan_from=how, delivery=delivery, codec=d.codec,
                      differences=differences)
