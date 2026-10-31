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
    "blanking_inexact": "Blanking pas à la ligne exacte",
    "frame_change": "Changement de cadre",
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
    "format_container": "Conteneur",
    "format_codec": "Codec",
    "format_picture": "Profondeur et échantillonnage",
    "format_resolution": "Résolution",
    "format_frame_rate": "Cadence",
    "format_color_tags": "Balises de colorimétrie",
    "integrity": "Intégrité du fichier",
    "alpha_channel": "Canal alpha",
    "audio_not_analysed": "Audio non analysé",
    "range_content_mismatch": "Contenu en plage pleine annoncé en plage légale",
    "range_tag_suspect": "Plage pleine annoncée, contenu en plage légale",
    "delivery_conversion_required": "Conversion pour la livraison",
    "scan_flag_mismatch": "Drapeau de balayage incorrect",
    "scan_interlaced": "Master entrelacé",
}

SEVERITY_LABELS = {"blocking": "bloquant", "major": "majeur", "minor": "mineur", "info": "info"}
SEVERITY_ORDER = ("blocking", "major", "minor", "info")

# Event types that are about the picture: they get a thumbnail with --thumbnails.
VIDEO_TYPES = frozenset({
    "white_clip", "black_crush", "gamut", "freeze", "isolated_black_frame", "duplicate_frame", "pse", "letterbox",
    "blanking_inexact", "frame_change", "structure_bars_present",
})


TECHNICAL_LABEL = "Rapport technique"


def status_label(status: str, indicative: bool, technical: bool = False) -> str:
    """Verdict as shown to the user. A draft profile never yields CONFORME (CLAUDE.md principle 7);
    a technical profile never yields CONFORME nor NON-CONFORME."""
    if technical:
        return TECHNICAL_LABEL
    if not indicative:
        return status
    return "INDICATIF : NON-CONFORME" if status == "NON-CONFORME" else "INDICATIF : sans anomalie bloquante"


def type_label(event_type: str) -> str:
    return TYPE_LABELS.get(event_type, event_type)


def number(value: float, digits: int = 1) -> str:
    """French decimal comma."""
    return f"{value:.{digits}f}".replace(".", ",")
