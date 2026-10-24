"""What PAD Guard can measure: the single source of the refusals and of the formats shown to the user.

A file outside these capabilities is refused before any measurement, with a message that names
what was found. A file inside them is analysed; a difference with the profile of the client
(codec, resolution, frame rate…) is an anomaly of the report, never a refusal (decision of
Damien, 24 October 2026).
"""

from __future__ import annotations

from fractions import Fraction
from typing import NamedTuple

import av

# Frame rates the measurements support. Nothing else may assume a rate: durations and timecodes
# always come from the rate read in probe.json.
MEASURABLE_RATES: tuple[Fraction, ...] = (
    Fraction(24000, 1001), Fraction(24), Fraction(25), Fraction(30000, 1001), Fraction(30),
    Fraction(50), Fraction(60000, 1001), Fraction(60),
)

class Layout(NamedTuple):
    bits: int  # per component
    hsub: int  # chroma subsampling, horizontal and vertical
    vsub: int


# Decoded pixel formats the measurement code reads (FFmpeg names): planar Y'CbCr, 8, 10 or 12 bits,
# 4:2:0, 4:2:2 or 4:4:4. An alpha plane (yuva*) is ignored by the measurements and reported.
LAYOUTS: dict[str, Layout] = {
    "yuv420p": Layout(8, 2, 2), "yuv422p": Layout(8, 2, 1), "yuv444p": Layout(8, 1, 1),
    "yuv420p10le": Layout(10, 2, 2), "yuv422p10le": Layout(10, 2, 1), "yuv444p10le": Layout(10, 1, 1),
    "yuv420p12le": Layout(12, 2, 2), "yuv422p12le": Layout(12, 2, 1), "yuv444p12le": Layout(12, 1, 1),
    "yuva422p10le": Layout(10, 2, 1), "yuva444p10le": Layout(10, 1, 1),
    "yuva422p12le": Layout(12, 2, 1), "yuva444p12le": Layout(12, 1, 1),
}
MEASURABLE_PIX_FMTS: tuple[str, ...] = tuple(LAYOUTS)

# Codec families known to decode to a measurable pixel format (shown by the interface).
FAMILIES: tuple[str, ...] = ("ProRes (Proxy à 4444 XQ)", "DNxHD / DNxHR (LB à 444)", "H.264 / AVC-Intra / XAVC")

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
        "depths": sorted({layout.bits for layout in LAYOUTS.values()}),
        "summary": " · ".join([*FAMILIES, ", ".join(rates)]),
        "extensions": [f".{c.lower()}" for c in CONTAINERS],
    }


SAMPLINGS = ("4:2:0", "4:2:2", "4:4:4", "rgb")


def pixel_info(pix_fmt: str | None) -> dict | None:
    """Bit depth, chroma sampling ('4:2:2'… or 'rgb') and alpha of an FFmpeg pixel format.

    None: unknown name, or a layout PAD Guard does not describe (Bayer, palette, 4:1:1…).
    """
    if not pix_fmt:
        return None
    try:
        fmt = av.VideoFormat(pix_fmt)
    except (ValueError, TypeError):
        return None
    if fmt.is_bayer or fmt.has_palette or not fmt.components:
        return None
    if fmt.is_rgb:
        sampling = "rgb"
    else:
        sampling = {(16, 16): "4:4:4", (8, 16): "4:2:2", (8, 8): "4:2:0"}.get(
            (fmt.chroma_width(16), fmt.chroma_height(16)))
        if sampling is None or len(fmt.components) < 3:
            return None
    return {"bit_depth": fmt.components[0].bits, "sampling": sampling,
            "alpha": any(c.is_alpha for c in fmt.components)}
