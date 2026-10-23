"""Write a draft profile, and the YAML of reviewed profiles, with one comment per value (SPEC §13).

Files of a draft ``<name>``, in ``profiles/drafts/``:

* ``<name>.yaml``: meta (status draft, source PDF and its SHA-256, proposed norms), the checked
  values, each with ``# A VERIFIER (p. N) « citation »``; fields in conflict or with an invalid
  citation are written ``null`` with the candidates in comment; fields not found are absent
  (inherited from a norm, so capped at minor) and listed at the top;
* ``<name>.findings.json``: every finding with its status, read by ``review-profile``;
* ``<name>.llm.jsonl``: the raw answers of the model, one line per page batch.

The three files are written together at the end, never half.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import yaml

from pad_checker.draft.extract import OK, Extraction, FieldResult

ORDER = ("meta", "format", "video", "audio", "structure", "rules", "llm", "sources")
QUOTE_CHARS = 160


def scalar(value: Any) -> str:
    """One-line YAML for a value (flow style for lists and mappings)."""
    return yaml.safe_dump(value, default_flow_style=True, allow_unicode=True, width=10_000).strip().removesuffix("\n...")


def one_line(text: str, limit: int = QUOTE_CHARS) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def nest(flat: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for path, value in flat.items():
        *parents, last = path.split(".")
        node = out
        for p in parents:
            node = node.setdefault(p, {})
        node[last] = value
    return out


def dump(data: dict[str, Any], comments: dict[str, str] | None = None, header: list[str] | None = None) -> str:
    """YAML of a profile, sections in profile order, ``comments`` keyed by dotted path."""
    comments = comments or {}
    lines = [f"# {h}" if h else "#" for h in header or []]
    if lines:
        lines.append("")
    keys = sorted(data, key=lambda k: ORDER.index(k) if k in ORDER else len(ORDER))
    for key in keys:
        _emit(lines, key, data[key], 0, key, comments)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _emit(lines: list[str], key: str, value: Any, depth: int, path: str, comments: dict[str, str]) -> None:
    pad = "  " * depth
    note = f"  # {comments[path]}" if path in comments else ""
    name = key if key in ("if", "else") or yaml.safe_load(f"{key}: 0") == {key: 0} else json.dumps(key)
    if isinstance(value, dict) and value and path != "sources" and not path.startswith("sources."):
        lines.append(f"{pad}{name}:{note}")
        for k, v in value.items():
            _emit(lines, k, v, depth + 1, f"{path}.{k}", comments)
    elif path == "sources" and isinstance(value, dict):
        lines.append(f"{pad}{name}:")
        for k, v in value.items():
            lines.append(f"{pad}  {k}: {scalar(v)}")
    elif isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
        lines.append(f"{pad}{name}:{note}")
        for v in value:
            lines.append(f"{pad}  - {scalar(v)}")
    else:
        lines.append(f"{pad}{name}: {scalar(value)}{note}")


def _comment(r: FieldResult) -> str:
    if r.status == OK:
        f = next(f for f in r.findings if f.status == OK and f.value == r.value)
        others = sorted({g.page for g in r.findings if g.status == OK} - {f.page})
        also = f" ; aussi p. {', '.join(map(str, others))}" if others else ""
        unit = f" [{f.unit}]" if f.unit else ""
        return f"A VERIFIER (p. {f.page}) « {one_line(f.quote)} »{unit}{also}"
    candidates = " | ".join(f"{scalar(f.value)} (p. {f.page}, {f.status}{': ' + f.reason if f.reason else ''}) "
                            f"« {one_line(f.quote, 80)} »" for f in r.findings)
    return f"{r.status} : {candidates}"


def draft_text(x: Extraction, meta: dict[str, Any]) -> str:
    values = {r.path: r.value for r in x.fields}
    comments = {r.path: _comment(r) for r in x.fields}
    data = {"meta": meta, **nest(values)}
    counts = {s: sum(r.status == s for r in x.fields) for s in sorted({r.status for r in x.fields})}
    header = [
        f"BROUILLON de profil « {meta['name']} » produit par pad-checker draft-profile : NE PAS UTILISER EN L'ÉTAT.",
        f"Source : {meta['source_pdf']} (SHA-256 {x.pdf_sha256}), {x.pages} pages.",
        f"Modèle local : {x.model}, consigne {x.prompt_version}, {x.batches} lots de pages.",
        "Chaque valeur est à vérifier (A VERIFIER) : la citation a été retrouvée dans la page et contient le nombre,",
        "mais seul un humain peut confirmer le sens. À relire avec : pad-checker review-profile <ce fichier>.",
        "Statuts : " + ", ".join(f"{n} {s}" for s, n in counts.items()) + f", {len(x.not_found)} champ(s) non trouvé(s).",
        "",
        "Champs non trouvés dans le document (absents : hérités d'une norme, donc plafonnés à minor, ou à fixer) :",
        *[f"  - {p}" for p in x.not_found],
    ]
    return dump(data, comments, header)


def findings_json(x: Extraction, meta: dict[str, Any]) -> str:
    data = {"meta": meta, "model": x.model, "prompt_version": x.prompt_version, "pdf_sha256": x.pdf_sha256,
            "pages": x.pages, "batches": x.batches, "fields": [r.to_json() for r in x.fields],
            "not_found": x.not_found}
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def paths_for(out_dir: Path, name: str) -> dict[str, Path]:
    return {"yaml": out_dir / f"{name}.yaml", "findings": out_dir / f"{name}.findings.json",
            "log": out_dir / f"{name}.llm.jsonl"}


def write_draft(out_dir: Path, name: str, x: Extraction, meta: dict[str, Any]) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = paths_for(out_dir, name)
    texts = {
        "yaml": draft_text(x, meta),
        "findings": findings_json(x, meta),
        "log": "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in x.log),
    }
    temps = {}
    try:
        for key, text in texts.items():
            tmp = targets[key].with_name(targets[key].name + ".tmp")
            tmp.write_text(text, encoding="utf-8", newline="\n")
            temps[key] = tmp
        for key, tmp in temps.items():
            os.replace(tmp, targets[key])
    finally:
        for tmp in temps.values():
            tmp.unlink(missing_ok=True)
    return targets
