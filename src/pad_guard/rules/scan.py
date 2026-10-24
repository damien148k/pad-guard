"""Scan rule: the scan seen in the pictures decides, not the container flag alone (SPEC §12.5).

With a progressive profile (``format.field_order: progressive``) and a determined detection:

- progressive pictures under an interlaced flag: the pictures are right, the label is wrong
  (``scan_flag_mismatch``, to be fixed at export);
- interlaced pictures: the master really is interlaced (``scan_interlaced``). Its severity is the
  profile's: a broadcaster may accept interlaced masters for a transition period. No rule reads
  today's date (reproducibility): a later version of the profile raises the severity.

Otherwise (interlaced profile, detection undetermined, flag absent) the flag check of the probe
(``field_order``, type ``format``) applies as it is.
"""

from __future__ import annotations

from dataclasses import dataclass

from pad_guard.measure.models import Measurements
from pad_guard.measure.scan import SCAN_LABELS
from pad_guard.probe.models import ProbeResult
from pad_guard.rules.profile import Profile

CHECK_ID = "field_order"  # probe check replaced by this rule when it decides


@dataclass(frozen=True)
class ScanRule:
    decided: bool  # False: the probe check field_order applies
    event_type: str | None  # scan_flag_mismatch | scan_interlaced | None (conforming)
    title: str
    actual: str  # French: detected scan and flag, for the format table and the event


def evaluate(probe: ProbeResult, m: Measurements, profile: Profile) -> ScanRule:
    s, flag, flag_scan = m.scan, probe.video.field_order or "absent", probe.video.scan_flag
    actual = (f"détecté : {SCAN_LABELS[s.detected]} ({s.combed_frames} image(s) peignée(s) sur {s.moving_frames} "
              f"en mouvement) ; drapeau : {flag} ({SCAN_LABELS[flag_scan]})")
    if profile.format.field_order != "progressive" or s.detected == "undetermined":
        return ScanRule(False, None, "", actual)
    if s.detected == "interlaced":
        return ScanRule(True, "scan_interlaced", f"Master entrelacé (drapeau {flag}) : le profil attend du progressif",
                        actual)
    if flag_scan == "interlaced":
        return ScanRule(True, "scan_flag_mismatch",
                        f"Drapeau de balayage incorrect ({flag}) sur un master progressif : "
                        "corriger l'étiquette à l'export", actual)
    if flag_scan == "unknown":
        return ScanRule(False, None, "", actual)  # no flag: the probe check reports it
    return ScanRule(True, None, "", actual)
