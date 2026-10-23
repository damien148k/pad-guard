"""Deterministic check of a model finding against the PDF text (SPEC §13).

A quote counts only if it is found in the text of the page it names, after normalisation
(Unicode compatibility forms, so ligatures and non-breaking spaces; typographic apostrophes,
quotes, dashes and minus signs; hyphenation at line ends; runs of white space; case). A number
counts only if the quote contains it (decimal comma or point, typographic minus).
"""

from __future__ import annotations

import math
import re
import unicodedata
from fractions import Fraction
from typing import Any

_CHARS = str.maketrans({
    "‘": "'", "’": "'", "ʼ": "'", "´": "'", "`": "'",
    "“": '"', "”": '"', "«": '"', "»": '"',
    "−": "-", "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
    "­": "",  # soft hyphen
})
_HYPHEN_BREAK = re.compile(r"(\w)-\s*\n\s*(\w)")
_SPACES = re.compile(r"\s+")
_SIGN_GAP = re.compile(r"(^|[\s(\[:;=])([-+])\s+(?=\d)")  # "- 23 LUFS" -> "-23 LUFS"
_NUMBER = re.compile(r"[-+]?\d+(?:[.,]\d+)?")
_TIMECODE = re.compile(r"^\d{2}:\d{2}:\d{2}[:;]\d{2}$")
_RATE = re.compile(r"^(\d+)/(\d+)$")


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_CHARS)
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    text = _SPACES.sub(" ", text).strip().casefold()
    return text.replace(" :", ":").replace(" ;", ";")


def quote_in(quote: str, page_text: str) -> bool:
    q = normalise(quote).strip(" .\"'…")
    return bool(q) and q in normalise(page_text)


_MIN_SEC = re.compile(r"(\d+)\s*'\s*(\d{2})\b")  # 2'00 = 120 s
_KHZ = re.compile(r"(\d+(?:[.,]\d+)?)\s*khz")


def numbers(text: str) -> list[tuple[float, str]]:
    """(number, text right after it) for every number of ``text``, plus 2'00 as 120 and 48 kHz as 48000."""
    text = _SIGN_GAP.sub(r"\1\2", normalise(text))
    out = [(float(m[0].replace(",", ".")), text[m.end(): m.end() + 12].lstrip()) for m in _NUMBER.finditer(text)]
    out += [(int(m[1]) * 60 + int(m[2]), "s") for m in _MIN_SEC.finditer(text)]
    out += [(float(m[1].replace(",", ".")) * 1000, "hz") for m in _KHZ.finditer(text)]
    # French thousands: "1.000 Hz", "48 000 Hz" (also read above as 1.0 and 48, 0).
    out += [(float(m[1] + m[2]), text[m.end(): m.end() + 12].lstrip()) for m in _THOUSANDS.finditer(text)]
    return out


_THOUSANDS = re.compile(r"(?<![\d.,])(\d{1,3})[. ](\d{3})(?![\d.,])")
_LONG = re.compile(r"superieure? (a|de) 2|> ?2 ?(min|')|programmes? longs?")
_SHORT = re.compile(r"inferieure? ou egale? (a|de) 2|<= ?2|≤ ?2|programmes? courts?|bandes? annonces?")


def loudness_context(path: str, quote: str, page_text: str) -> str | None:
    """For loudness values of long or short programmes: None if the last duration mentioned before
    the quote in the page fits the field, else a French reason. Documents often give both sets
    one after the other, and the quote alone does not say which programmes it is about."""
    kind = "long" if ".loudness.long." in path else "short" if ".loudness.short." in path else None
    if kind is None:
        return None
    from pad_checker.draft.vocabulary import plain

    text, q = plain(normalise(page_text)), plain(normalise(quote)).strip(" .\"'…")
    at = text.find(q)
    if at < 0:
        return None
    before = text[:at]
    last_long = max((m.end() for m in _LONG.finditer(before)), default=-1)
    last_short = max((m.end() for m in _SHORT.finditer(before)), default=-1)
    if kind == "long" and last_short > last_long:
        return "le passage cité concerne les programmes courts"
    if kind == "short" and last_long > last_short:
        return "le passage cité concerne les programmes longs"
    return None


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)


def value_in_quote(value: Any, quote: str, unit: str | None = None) -> str | None:
    """None if every number of ``value`` is in ``quote`` (followed by ``unit``, a regex, if given),
    else a French reason.

    Text without digits (a codec name, « progressive ») and booleans are not checked here:
    the quote itself has been found in the page.
    """
    found = numbers(quote)
    for v in _numbers_of(value):
        hits = [after for n, after in found if _close(v, n)]
        if not hits:
            return f"la citation ne contient pas le nombre {v:g}"
        if unit and not any(re.match(unit, after) for after in hits):
            return f"le nombre {v:g} n'est pas suivi de l'unité attendue dans la citation"
    if isinstance(value, str) and _TIMECODE.match(value) and value[:8] not in normalise(quote):
        return f"la citation ne contient pas le timecode {value}"
    return None


def _numbers_of(value: Any) -> list[float]:
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, str):
        m = _RATE.match(value)
        if m:  # frame rate "25/1": the document writes 25 (or 29,97 for 30000/1001)
            return [round(float(Fraction(int(m[1]), int(m[2]))), 2)]
        return []  # timecodes are checked as text, other strings are words
    if isinstance(value, list):
        return [n for item in value for n in _numbers_of(item)]
    if isinstance(value, dict):
        return [n for item in value.values() for n in _numbers_of(item)]
    return []
