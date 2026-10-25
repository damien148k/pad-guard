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
    rgb: bool = False  # planar G, B, R (FFmpeg gbrp*): converted to Y'CbCr before measuring
    full_range: bool = False  # the pixel format itself says full range (FFmpeg yuvj*)


# Decoded pixel formats the measurement code reads (FFmpeg names): planar Y'CbCr or R'G'B', 8, 10
# or 12 bits, 4:2:0, 4:2:2 or 4:4:4. An alpha plane (yuva*, gbrap*) is ignored and reported.
LAYOUTS: dict[str, Layout] = {
    "yuvj420p": Layout(8, 2, 2, full_range=True), "yuvj422p": Layout(8, 2, 1, full_range=True),
    "yuvj444p": Layout(8, 1, 1, full_range=True),
    "gbrp": Layout(8, 1, 1, rgb=True), "gbrp10le": Layout(10, 1, 1, rgb=True), "gbrp12le": Layout(12, 1, 1, rgb=True),
    "gbrap10le": Layout(10, 1, 1, rgb=True), "gbrap12le": Layout(12, 1, 1, rgb=True),
    "yuv420p": Layout(8, 2, 2), "yuv422p": Layout(8, 2, 1), "yuv444p": Layout(8, 1, 1),
    "yuv420p10le": Layout(10, 2, 2), "yuv422p10le": Layout(10, 2, 1), "yuv444p10le": Layout(10, 1, 1),
    "yuv420p12le": Layout(12, 2, 2), "yuv422p12le": Layout(12, 2, 1), "yuv444p12le": Layout(12, 1, 1),
    "yuva422p10le": Layout(10, 2, 1), "yuva444p10le": Layout(10, 1, 1),
    "yuva422p12le": Layout(12, 2, 1), "yuva444p12le": Layout(12, 1, 1),
}
MEASURABLE_PIX_FMTS: tuple[str, ...] = tuple(LAYOUTS)
PIX_FMTS_TEXT = "Y'CbCr 4:2:0, 4:2:2 ou 4:4:4, ou RVB, en 8, 10 ou 12 bits"  # what LAYOUTS covers, in words

# Codec families known to decode to a measurable pixel format (shown by the interface).
FAMILIES: tuple[str, ...] = ("ProRes (Proxy à 4444 XQ)", "DNxHD / DNxHR (LB à 444)", "XAVC / AVC-Intra / H.264",
                             "XDCAM HD422 (MPEG-2)", "HEVC", "non compressé (v210, r210)")

CONTAINERS: tuple[str, ...] = ("MOV", "MP4", "MXF")

# HDR transfers (PQ, HLG) and the BT.2020 colour space: measured from Phase 7 (luminance in cd/m²,
# BT.2100). Measured today as SDR BT.709 they would give false levels: refused.
HDR_TRANSFERS = frozenset({"smpte2084", "arib-std-b67"})
WIDE_GAMUT = frozenset({"bt2020nc", "bt2020c", "bt2020"})

# Luma coefficients (Kr, Kb) of the colour matrices, by ffprobe color_space: definitions, not thresholds.
# ITU-R BT.709-6, part 2, item 3.2: « E'Y = 0.2126 E'R + 0.7152 E'G + 0.0722 E'B ».
# SD (bt470bg: 625 lines, smpte170m: 525 lines): ITU-R BT.601 E'Y = 0.299 E'R + 0.587 E'G + 0.114 E'B.
# A VERIFIER : BT.601 n'est pas encore dans normes/sources/TV (source à ajouter, décision de Damien
# du 24/10/2026 : coefficients usuels en attendant).
MATRICES: dict[str, tuple[float, float]] = {
    "bt709": (0.2126, 0.0722),
    "bt470bg": (0.299, 0.114),
    "smpte170m": (0.299, 0.114),
}


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
