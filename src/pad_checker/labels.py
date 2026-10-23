"""French labels shown to the user for anomaly types and severities."""

from __future__ import annotations

TYPE_LABELS = {
    "white_clip": "Blancs hors tolérance",
    "black_crush": "Noirs hors tolérance",
    "gamut": "Gamut RVB hors limites",
    "freeze": "Image figée",
    "isolated_black_frame": "Image noire isolée",
    "duplicate_frame": "Image dupliquée",
    "pse": "Flashs (PSE)",
    "letterbox": "Format d'image",
    "audio_loudness": "Loudness intégré",
    "audio_true_peak": "True peak",
    "audio_short_term_excursion": "Loudness short term",
    "audio_lra": "LRA",
    "audio_silent_track": "Piste silencieuse",
    "audio_dual_mono_mismatch": "Double mono non identique",
    "audio_silence": "Silence",
    "audio_phase": "Opposition de phase",
    "audio_clipping": "Saturation numérique",
    "structure_bars": "Mire de tête",
    "structure_black": "Noir de tête ou de queue",
    "structure_timecode": "Timecode",
    "structure_bars_present": "Mire présente (amorce interdite)",
    "structure_black_too_long": "Noir de tête ou de queue trop long",
    "format": "Format du fichier",
    "integrity": "Intégrité du fichier",
    "delivery_conversion_required": "Conversion pour la livraison",
}

SEVERITY_LABELS = {"blocking": "bloquant", "major": "majeur", "minor": "mineur", "info": "info"}
SEVERITY_ORDER = ("blocking", "major", "minor", "info")

# Event types that are about the picture: they get a thumbnail with --thumbnails.
VIDEO_TYPES = frozenset({
    "white_clip", "black_crush", "gamut", "freeze", "isolated_black_frame", "duplicate_frame", "pse", "letterbox",
    "structure_bars_present",
})


def status_label(status: str, indicative: bool) -> str:
    """Verdict as shown to the user. A draft profile never yields CONFORME (CLAUDE.md principle 7)."""
    if not indicative:
        return status
    return "INDICATIF : NON-CONFORME" if status == "NON-CONFORME" else "INDICATIF : sans anomalie bloquante"


def type_label(event_type: str) -> str:
    return TYPE_LABELS.get(event_type, event_type)


def number(value: float, digits: int = 1) -> str:
    """French decimal comma."""
    return f"{value:.{digits}f}".replace(".", ",")
