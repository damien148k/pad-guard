"""Examples for the model from the validated profiles of other broadcasters (SPEC §13).

For each field, the citations of the profiles in ``profiles/`` with ``meta.status: validated``
show the model how a document phrased a value (« in this document, this sentence gave this
field »). The profiles of the broadcaster whose PDF is being read are always left out, or the
acceptance test on that broadcaster would be read from its own answers: same PDF (SHA-256 or
file name), same broadcaster, or same first word of the broadcaster or profile name
(« ARTE G.E.I.E. », « arte_uhd »). Leaving out one profile too many is the safe side.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from pad_guard.draft.vocabulary import plain

PER_FIELD = 2  # examples shown per field


@dataclass(frozen=True)
class Example:
    path: str
    value: Any
    source: str  # the citation of the validated profile
    broadcaster: str
    profile: str


@dataclass(frozen=True)
class Target:
    """The PDF being read: whose examples must not be shown."""

    name: str
    broadcaster: str | None = None
    pdf_sha256: str | None = None
    pdf_name: str | None = None


def _first_word(text: str | None) -> str:
    words = re.findall(r"[a-z0-9]+", plain(text or ""))
    return words[0] if words else ""


def same_broadcaster(meta: dict, target: Target) -> bool:
    if target.pdf_sha256 and meta.get("source_pdf_sha256") == target.pdf_sha256:
        return True
    if target.pdf_name and Path(str(meta.get("source_pdf") or "")).name == target.pdf_name:
        return True
    mine = {_first_word(meta.get("broadcaster")), _first_word(meta.get("name"))} - {""}
    theirs = {_first_word(target.broadcaster), _first_word(target.name)} - {""}
    return bool(mine & theirs)


def _get(data: dict, path: str) -> Any:
    node: Any = data
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _is_citation(source: str) -> bool:
    """A citation of the broadcaster's document, not a house note or an uncited value."""
    text = plain(source).lstrip()
    return bool(text) and not text.startswith(("lumiris", "a verifier", "pad guard"))


def collect(profiles_dir: Path, target: Target) -> dict[str, list[Example]]:
    """Examples by field path, from the validated profiles of other broadcasters, file name order."""
    out: dict[str, list[Example]] = {}
    for path in sorted(profiles_dir.glob("*.yaml")):
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            continue
        meta = raw.get("meta") or {}
        if meta.get("status") != "validated" or same_broadcaster(meta, target):
            continue
        for field, source in (raw.get("sources") or {}).items():
            value = _get(raw, field)
            if value is None or not isinstance(source, str) or not _is_citation(source):
                continue
            items = out.setdefault(field, [])
            if len(items) < PER_FIELD:
                items.append(Example(field, value, " ".join(source.split()), str(meta.get("broadcaster") or ""),
                                     path.name))
    return out


def prompt_block(examples: dict[str, list[Example]], paths: list[str]) -> str:
    from pad_guard.draft.write import scalar

    lines = []
    for p in paths:
        for e in examples.get(p, []):
            lines.append(f"- {p} : chez {e.broadcaster}, « {e.source} » a donné {scalar(e.value)}")
    return "\n".join(lines)
