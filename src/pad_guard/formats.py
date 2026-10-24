"""What PAD Guard can measure: the single source of the refusals and of the formats shown to the user.

A file outside these capabilities is refused before any measurement, with a message that names
what was found. A file inside them is analysed; a difference with the profile of the client
(codec, resolution, frame rate…) is an anomaly of the report, never a refusal (decision of
Damien, 24 October 2026).
"""

from __future__ import annotations

from fractions import Fraction

import av

# Frame rates the measurements support. Nothing else may assume a rate: durations and timecodes
# always come from the rate read in probe.json.
MEASURABLE_RATES: tuple[Fraction, ...] = (Fraction(25, 1),)

# Decoded pixel formats the measurement code reads (FFmpeg names).
MEASURABLE_PIX_FMTS: tuple[str, ...] = ("yuv422p10le",)

# Codec families known to decode to a measurable pixel format (shown by the interface).
FAMILIES: tuple[str, ...] = ("ProRes 422 (Proxy à HQ)", "DNxHR HQX", "DNxHD 10 bits")

CONTAINERS: tuple[str, ...] = ("MOV", "MXF")


def rate_label(fps: Fraction) -> str:
    """'25', '29,97', '23,976'."""
    return f"{float(fps):.3f}".rstrip("0").rstrip(".").replace(".", ",")


def rate_text(fps: Fraction) -> str:
    """'25/1 (25 i/s)', '30000/1001 (29,97 i/s)'."""
    return f"{fps.numerator}/{fps.denominator} ({rate_label(fps)} i/s)"


def decoder_available(codec_name: str) -> bool:
    """PyAV (the FFmpeg it embeds) has a decoder for this ffprobe codec name."""
    try:
        av.codec.Codec(codec_name, "r")
    except Exception:  # noqa: BLE001 - UnknownCodecError, ValueError: no decoder
        return False
    return True


def capabilities() -> dict:
    """Formats PAD Guard measures, for the interface and the CLI help (French)."""
    rates = [f"{rate_label(r)} i/s" for r in MEASURABLE_RATES]
    return {
        "families": list(FAMILIES),
        "containers": list(CONTAINERS),
        "rates": rates,
        "pix_fmts": list(MEASURABLE_PIX_FMTS),
        "summary": " · ".join([*FAMILIES, " ou ".join(rates)]),
        "extensions": [f".{c.lower()}" for c in CONTAINERS],
    }
