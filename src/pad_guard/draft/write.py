"""Write a draft profile, and the YAML of reviewed profiles, with one comment per value (SPEC §13).

Files of a draft ``<name>``, in ``profiles/drafts/``:

* ``<name>.yaml``: meta (status draft, source PDF and its SHA-256, proposed norms), the checked
  values, each with ``# A VERIFIER (p. N) « citation »``; implausible values are written with
  ``# INVRAISEMBLABLE``; fields in conflict or with an invalid citation are written ``null`` with
  the candidates in comment; fields not found, and fields for which the document only refers to
  a norm, are absent (inherited from a norm, so capped at minor) and listed at the top, with the
  norms the document cites;
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

from pad_guard.draft.extract import IMPLAUSIBLE, NORM_REF, OK, Extraction, FieldResult, Finding, canonical
from pad_guard.draft.schema import MAX_FINDINGS

ORDER = ("meta", "format", "video", "audio", "structure", "rules", "llm", "sources")
QUOTE_CHARS = 160
CAPPED = "limite atteinte, propositions possiblement manquantes"


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


Norms = dict[str, tuple[str, bool, Finding]]  # key -> (title, file in normes/, first citation)


def rejected_others(r: FieldResult) -> list[Finding]:
    """Proposals refused by a check whose value differs from the kept one: the kept value may be
    incomplete (audio.groups: the AD tracks kept, VO and VF refused)."""
    return [f for f in r.findings if f.status not in (OK, IMPLAUSIBLE, NORM_REF) and f.value is not None
            and canonical(f.value) != canonical(r.value)]


def _comment(r: FieldResult) -> str:
    if r.status in (OK, IMPLAUSIBLE):
        f = next(f for f in r.findings if f.status == r.status and f.value == r.value)
        others = sorted({g.page for g in r.findings if g.status in (OK, IMPLAUSIBLE)} - {f.page})
        also = f" ; aussi p. {', '.join(map(str, others))}" if others else ""
        unit = f" [{f.unit}]" if f.unit else ""
        lead = "A VERIFIER" if r.status == OK else f"INVRAISEMBLABLE ({f.reason})"
        rejected = rejected_others(r)
        more = f" ; {len(rejected)} autre(s) proposition(s) rejetée(s) avec une autre valeur : valeur peut-être incomplète" \
            if rejected else ""
        return f"{lead} (p. {f.page}) « {one_line(f.quote)} »{unit}{also}{more}"
    candidates = " | ".join(f"{scalar(f.value)} (p. {f.page}, {f.status}{': ' + f.reason if f.reason else ''}) "
                            f"« {one_line(f.quote, 80)} »" for f in r.findings)
    return f"{r.status} : {candidates}"


def _norm_line(key: str, title: str, available: bool, f: Finding) -> str:
    where = f"normes/{key}.yaml" if available else "absente de normes/ : à ajouter ou à saisir à la main"
    return f"  - {title} ({where}) : p. {f.page} « {one_line(f.quote, 120)} »"


def draft_text(x: Extraction, meta: dict[str, Any], norms: Norms | None = None) -> str:
    norms = norms or {}
    kept = [r for r in x.fields if r.status != NORM_REF]  # a reference to a norm gives no value
    refs = [r for r in x.fields if r.status == NORM_REF]
    values = {r.path: r.value for r in kept}
    comments = {r.path: _comment(r) for r in kept}
    data = {"meta": meta, **nest(values)}
    counts = {s: sum(r.status == s for r in x.fields) for s in sorted({r.status for r in x.fields})}
    norm = meta.get("kind") == "norm"
    header = [
        f"BROUILLON de {'norme' if norm else 'profil'} « {meta['name']} » produit par pad-guard draft-profile : "
        "NE PAS UTILISER EN L'ÉTAT.",
        f"Source : {meta['source_pdf']} (SHA-256 {x.pdf_sha256}), {x.pages} pages.",
        f"Modèle local : {x.model}, consigne {x.prompt_version}, {x.batches} lots de pages, contexte {x.num_ctx} jetons.",
        "Chaque valeur est à vérifier (A VERIFIER) : la citation a été retrouvée dans la page et contient le nombre,",
        "mais seul un humain peut confirmer le sens. À relire avec : pad-guard review-profile <ce fichier>.",
        *[f"ATTENTION page {n} : {CAPPED} (limite de {MAX_FINDINGS} par réponse, même page par page) : à relire à la main."
          for n in x.capped_pages],
        "Statuts : " + ", ".join(f"{n} {s}" for s, n in counts.items()) + f", {len(x.not_found)} champ(s) non trouvé(s).",
        "",
        *(["Normes citées par le document (celles de normes/ proposées dans meta.extends ; review-profile confirme",
           "chaque renvoi, aucune valeur n'est recopiée) :"] if norm else
          ["Normes citées par le document (proposées dans meta.extends, après les autres : elles priment) :"]),
        *([_norm_line(k, *v) for k, v in norms.items()] or ["  (aucune)"]),
        "",
        *(["Champs pour lesquels le document renvoie à une norme sans écrire la valeur (absents : fournis par la",
           "norme citée si review-profile confirme le renvoi) :"] if norm else
          ["Champs pour lesquels le document renvoie à une norme sans écrire la valeur (absents : hérités de la",
           "norme : exigences du client si review-profile confirme le renvoi, sinon recommandations plafonnées à minor) :"]),
        *([f"  - {r.path} -> {_ref(r)}" for r in refs] or ["  (aucun)"]),
        "",
        ("Champs non trouvés dans le document (absents de la norme) :" if norm else
         "Champs non trouvés dans le document (absents : hérités d'une norme, donc plafonnés à minor, ou à fixer) :"),
        *[f"  - {p}" for p in x.not_found],
    ]
    return dump(data, comments, header)


def _ref(r: FieldResult) -> str:
    f = next(f for f in r.findings if f.status == NORM_REF)
    return f"{f.norm} (p. {f.page}) « {one_line(f.quote, 100)} »"


def findings_json(x: Extraction, meta: dict[str, Any], norms: Norms | None = None) -> str:
    cited = [{"norm": k, "title": t, "available": a, "page": f.page, "quote": f.quote, "field": f.field}
             for k, (t, a, f) in (norms or {}).items()]
    data = {"meta": meta, "model": x.model, "prompt_version": x.prompt_version, "pdf_sha256": x.pdf_sha256,
            "pages": x.pages, "batches": x.batches, "num_ctx": x.num_ctx, "capped_pages": x.capped_pages, "cited_norms": cited,
            "fields": [r.to_json() for r in x.fields],
            "not_found": x.not_found}
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def paths_for(out_dir: Path, name: str) -> dict[str, Path]:
    return {"yaml": out_dir / f"{name}.yaml", "findings": out_dir / f"{name}.findings.json",
            "log": out_dir / f"{name}.llm.jsonl"}


def write_draft(out_dir: Path, name: str, x: Extraction, meta: dict[str, Any],
                norms: Norms | None = None) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    targets = paths_for(out_dir, name)
    texts = {
        "yaml": draft_text(x, meta, norms),
        "findings": findings_json(x, meta, norms),
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
