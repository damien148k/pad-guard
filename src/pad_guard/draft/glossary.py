"""Broadcaster vocabulary, reviewed by a human: normes/glossaire.yaml (SPEC §13).

For each extractable field of the profile: French and English synonyms, accepted units,
contexts to tell apart (long / short programme, HD / UHD, VO / VF…) and a plausible range.
It is used four ways, all deterministic:

* the terms found in a batch of pages select the fields whose glossary entry (and examples
  from validated profiles) is shown to the model;
* a quote that holds one of the field's terms has the vocabulary of the field (in addition to
  :data:`pad_guard.draft.vocabulary.KEYWORDS`);
* a value out of the plausible range, a cited unit not accepted for the field or a malformed
  timecode make the finding INVRAISEMBLABLE (value kept, shown in red at review);
* the norm aliases (« R128 », « R 128 »…) map a reference of the document to a file of normes/.

The plausible ranges are not norm values: they only catch reading errors (48 for 48 kHz,
a loudness taken for a true peak) and never reach a verdict. ``review-profile`` adds the terms
used by a broadcaster when the reviewer confirms it (:func:`add_term`).
"""

from __future__ import annotations

import json
import os
import re
from fractions import Fraction
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from pad_guard.draft.verify import normalise
from pad_guard.profiles.resolve import REPO_NORMS

GLOSSARY = REPO_NORMS / "glossaire.yaml"
_TIMECODE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})[:;](\d{2})$")
_RATE = re.compile(r"^(\d+)/(\d+)$")


class GlossaryError(Exception):
    """The glossary cannot be read. The message is user-facing (French)."""


class FieldTerms(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fr: list[str] = Field(default_factory=list)
    en: list[str] = Field(default_factory=list)
    unites: list[str] = Field(default_factory=list)
    contextes: list[str] = Field(default_factory=list)
    plage: tuple[float, float] | None = None
    forme: Literal["timecode", "cadence"] | None = None

    @property
    def terms(self) -> list[str]:
        return [*self.fr, *self.en]


class NormRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    titre: str
    alias: list[str]


class Glossary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meta: dict[str, Any]
    normes: dict[str, NormRef]
    champs: dict[str, FieldTerms]
    header: list[str] = Field(default_factory=list, exclude=True)  # leading comment lines, kept on rewrite
    path: Path | None = Field(default=None, exclude=True)

    def field(self, path: str) -> FieldTerms | None:
        return self.champs.get(path)

    def fields_in(self, text: str) -> list[str]:
        """Fields with at least one term in ``text``, glossary order."""
        hay = _plain(text)
        return [p for p, t in self.champs.items() if any(_has(hay, term) for term in t.terms)]

    def has_term(self, path: str, quote: str) -> bool:
        terms = self.champs.get(path)
        hay = _plain(quote)
        return bool(terms) and any(_has(hay, term) for term in terms.terms)

    def norms_in(self, text: str) -> list[str]:
        """Keys of the norms named in ``text`` (by one of their aliases), glossary order."""
        hay = _plain(text)
        return [k for k, n in self.normes.items() if any(_has(hay, a) for a in n.alias)]

    def prompt_block(self, paths: list[str]) -> str:
        """Glossary lines for the model, for ``paths`` only."""
        lines = []
        for p in paths:
            t = self.champs.get(p)
            if t is None:
                continue
            parts = [f"termes : {', '.join(t.terms)}"]
            if t.unites:
                parts.append(f"unités : {', '.join(t.unites)}")
            if t.contextes:
                parts.append(f"contextes à distinguer : {' ; '.join(t.contextes)}")
            lines.append(f"- {p} : " + " | ".join(parts))
        return "\n".join(lines)


def _plain(text: str) -> str:
    from pad_guard.draft.vocabulary import plain

    return plain(normalise(text))


def _has(hay: str, term: str) -> bool:
    needle = _plain(term)
    return bool(needle) and re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", hay) is not None


def load(path: Path = GLOSSARY) -> Glossary:
    if not path.is_file():
        raise GlossaryError(f"glossaire introuvable : {path}")
    text = path.read_text(encoding="utf-8")
    try:
        data = yaml.safe_load(text) or {}
        g = Glossary.model_validate(data)
    except (yaml.YAMLError, ValueError) as exc:
        raise GlossaryError(f"glossaire illisible ({path}) : {exc}") from None
    header = []
    for line in text.splitlines():
        if not line.startswith("#"):
            break
        header.append(line)
    g.header, g.path = header, path
    return g


def dump(g: Glossary) -> str:
    """Canonical text of the glossary: the header comment, then the data in a fixed layout."""
    def flow(items: list[Any]) -> str:
        return "[" + ", ".join(json.dumps(i, ensure_ascii=False) for i in items) + "]"

    lines = [*g.header, "", "meta:"]
    lines += [f"  {k}: {json.dumps(v, ensure_ascii=False)}" for k, v in g.meta.items()]
    lines += ["", "normes:"]
    for key, n in g.normes.items():
        lines += [f"  {key}:", f"    titre: {json.dumps(n.titre, ensure_ascii=False)}", f"    alias: {flow(n.alias)}"]
    lines += ["", "champs:"]
    for path, t in g.champs.items():
        lines.append(f"  {path}:")
        for key in ("fr", "en", "unites", "contextes"):
            if getattr(t, key):
                lines.append(f"    {key}: {flow(getattr(t, key))}")
        if t.plage is not None:
            lines.append(f"    plage: [{_num(t.plage[0])}, {_num(t.plage[1])}]")
        if t.forme:
            lines.append(f"    forme: {t.forme}")
    return "\n".join(lines) + "\n"


def _num(x: float) -> str:
    return str(int(x)) if float(x).is_integer() else repr(float(x))


def add_term(g: Glossary, path: str, lang: Literal["fr", "en"], term: str) -> bool:
    """Add ``term`` to the field ``path`` and rewrite the glossary file. False if already known."""
    term = " ".join(term.split())
    entry = g.champs.setdefault(path, FieldTerms())
    if not term or any(_plain(t) == _plain(term) for t in entry.terms):
        return False
    getattr(entry, lang).append(term)
    if g.path is not None:
        tmp = g.path.with_name(g.path.name + ".tmp")
        tmp.write_text(dump(g), encoding="utf-8", newline="\n")
        os.replace(tmp, g.path)
    return True


def _numbers(value: Any, forme: str | None) -> list[float]:
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [float(value)]
    if isinstance(value, str) and forme == "cadence" and (m := _RATE.match(value)):
        return [float(Fraction(int(m[1]), int(m[2])))] if int(m[2]) else [float("inf")]
    if isinstance(value, list):
        return [n for v in value for n in _numbers(v, forme)]
    if isinstance(value, dict):
        return [n for v in value.values() for n in _numbers(v, forme)]
    return []


def _unit_key(unit: str) -> str:
    return re.sub(r"\s+", "", _plain(unit))


def unit_accepted(unit: str, accepted: list[str]) -> bool:
    """The cited unit is one of ``accepted``, or starts with one of at least 4 characters
    (« dBTP max », « images par secondes »): « dB » never covers « dBFS »."""
    cited = _unit_key(unit)
    keys = {_unit_key(u) for u in accepted}
    return cited in keys or any(len(k) >= 4 and cited.startswith(k) for k in keys)


def implausible(g: Glossary, path: str, value: Any, unit: str | None) -> str | None:
    """None if the value is plausible for the field, else a French reason (INVRAISEMBLABLE)."""
    t = g.champs.get(path)
    if t is None:
        return None
    if unit and t.unites and not unit_accepted(unit, t.unites):
        return f"unité citée « {unit} » incompatible avec le champ (attendu : {', '.join(t.unites)})"
    if t.forme == "timecode" and isinstance(value, str):
        m = _TIMECODE.match(value)
        if not m or int(m[1]) > 23 or int(m[2]) > 59 or int(m[3]) > 59 or int(m[4]) > 59:
            return f"timecode « {value} » mal formé (attendu HH:MM:SS:FF)"
    if t.plage is not None:
        lo, hi = t.plage
        out = [n for n in _numbers(value, t.forme) if not lo <= n <= hi]
        if out:
            return f"valeur {out[0]:g} hors de la plage vraisemblable [{_num(lo)} ; {_num(hi)}]"
    return None
