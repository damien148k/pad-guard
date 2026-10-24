"""review-profile: a human goes through a draft, field by field, and validates the profile (SPEC §13).

For each extracted field the reviewer sees the proposed value, its page and quote, the value of
the profile used as base and the value of the norms (information), then accepts, chooses one
candidate of a conflict, corrects, keeps the base value or leaves the field empty (it is then
inherited from a norm, as a recommendation capped at minor). Values the PDF did not give are
taken from the base profile (by default the existing ``profiles/<name>.yaml``, else the template
``profiles/modeles/gabarit_diffuseur.yaml``) and flagged A VERIFIER when uncited.

The norms the document explicitly refers to (« conforme à EBU R 128 ») are confirmed one by one:
a confirmed reference goes to ``meta.refers_to`` and the values of that norm the client does not
write become requirements of the client, not capped (CLAUDE.md principle 2).

Implausible values (out of the glossary range, or cited with a unit the field does not accept)
are shown in red. When the reviewer corrects or completes a value, the term the broadcaster uses
may be added to the glossary (normes/glossaire.yaml), after confirmation.

Before the profile is written, the rules that can block or fail a PAD while their value would
come from a norm only (so be capped at minor) are listed: the most dangerous trap.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from pad_guard.draft import glossary as glossary_mod
from pad_guard.draft.extract import CONFLICT, IMPLAUSIBLE, NORM_REF, OK
from pad_guard.draft.schema import catalogue, check_value
from pad_guard.draft.write import CAPPED, dump, one_line, scalar
from pad_guard.profiles.resolve import (
    HOUSE,
    ResolvedProfile,
    capped_norm_values,
    leaves,
    load_norm,
    norms_dir_for,
    read_yaml,
    resolve_profile,
)
from pad_guard.rules.engine import Draft, depends_on
from pad_guard.rules.profile import ProfileError

ROOT = Path(__file__).resolve().parents[3]
TEMPLATE = ROOT / "profiles" / "modeles" / "gabarit_diffuseur.yaml"

Ask = Callable[[str], str]
Say = Callable[[str], None]


class ReviewError(Exception):
    """The review cannot go on. The message is user-facing (French)."""


@dataclass
class Decision:
    path: str
    action: str  # accept | correct | empty | keep
    value: Any = None
    source: str | None = None


@dataclass
class Review:
    draft: Path
    meta: dict[str, Any]
    fields: list[dict]  # findings.json "fields"
    base: Path
    decisions: list[Decision] = field(default_factory=list)
    glossary: glossary_mod.Glossary | None = None
    cited_norms: list[dict] = field(default_factory=list)  # findings.json "cited_norms"
    capped_pages: list[int] = field(default_factory=list)  # findings.json "capped_pages"
    references: list[dict] = field(default_factory=list)  # confirmed: {norm, source} for meta.refers_to


def load(draft: Path, base: Path | None) -> Review:
    sidecar = draft.with_name(draft.stem + ".findings.json")
    if not sidecar.is_file():
        raise ReviewError(f"{sidecar.name} absent à côté de {draft} : relancer « draft-profile »")
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    meta = data["meta"]
    if base is None:
        own = ROOT / "profiles" / f"{meta['name']}.yaml"
        base = own if own.is_file() else TEMPLATE
    terms = norms_dir_for(base) / glossary_mod.GLOSSARY.name
    try:
        g = glossary_mod.load(terms) if terms.is_file() else None
    except glossary_mod.GlossaryError as exc:
        raise ReviewError(str(exc)) from None
    return Review(draft=draft, meta=meta, fields=data["fields"], base=base, glossary=g,
                  cited_norms=data.get("cited_norms", []), capped_pages=data.get("capped_pages", []))


def norm_values(extends: list[str], norms_dir: Path) -> dict[str, tuple[Any, str]]:
    """Value of each path in the international norms of ``extends`` (the last one wins)."""
    out: dict[str, tuple[Any, str]] = {}
    for name in extends:
        if name == HOUSE or not (norms_dir / f"{name}.yaml").is_file():
            continue
        norm = load_norm(norms_dir / f"{name}.yaml")
        title = norm.meta.document.title.split(" — ")[0]
        for path, value in leaves({k: v for k, v in norm.raw.items() if k != "sources"}):
            out[path] = (value, title)
    return out


def _get(data: dict, path: str) -> Any:
    node: Any = data
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _set(data: dict, path: str, value: Any) -> None:
    *parents, last = path.split(".")
    node = data
    for p in parents:
        node = node.setdefault(p, {})
    node[last] = value


def _delete(data: dict, path: str) -> None:
    *parents, last = path.split(".")
    node = data
    for p in parents:
        if p not in node:
            return
        node = node[p]
    node.pop(last, None)


def _citation(doc: str, finding: dict) -> str:
    return f"{doc} p. {finding['page']} : « {one_line(finding['quote'], 300)} »"


ASKED = (OK, CONFLICT, IMPLAUSIBLE, NORM_REF)


def ask_fields(review: Review, ask: Ask, say: Say, everything: bool = False, alert: Say | None = None) -> list[dict]:
    """Ask about the fields to verify (A_VERIFIER, INVRAISEMBLABLE, RENVOI_NORME) and in conflict;
    with ``everything``, also about the fields whose proposals were all refused. Returns the fields
    not asked about (they keep the value of the base profile). ``alert`` prints in red."""
    alert = alert or say
    for n in review.capped_pages:
        alert(f"Page {n} : {CAPPED} (relire cette page du document à la main).")
    specs = {s.path: s for s in catalogue()}
    base_raw = read_yaml(review.base)
    norms = norm_values(review.meta.get("extends", []), norms_dir_for(review.base))
    doc = review.meta.get("source_document", "document")
    asked = [f for f in review.fields if everything or f["status"] in ASKED]
    skipped = [f for f in review.fields if f not in asked]
    total = len(asked)
    for i, f in enumerate(asked, start=1):
        path = f["path"]
        say(f"\n[{i}/{total}] {path} — {f['description']}")
        good = [x for x in f["findings"] if x["status"] in (OK, CONFLICT, IMPLAUSIBLE)]
        candidates = good if f["status"] == CONFLICT else []
        if f["status"] in (OK, IMPLAUSIBLE):
            first = next(x for x in good if x["value"] == f["value"] and x["status"] == f["status"])
            say(f"  Proposé : {scalar(f['value'])} (p. {first['page']}) « {one_line(first['quote'], 200)} »")
            if f["status"] == IMPLAUSIBLE:
                alert(f"  INVRAISEMBLABLE : {first['reason']}")
            rejected = [x for x in f["findings"] if x["status"] not in (OK, IMPLAUSIBLE, NORM_REF)
                        and x["value"] is not None and x["value"] != f["value"]]
            if rejected:
                alert(f"  {len(rejected)} autre(s) proposition(s) rejetée(s) avec une autre valeur : "
                      "la valeur proposée est peut-être incomplète")
                for x in rejected:
                    say(f"      {one_line(scalar(x['value']), 120)} (p. {x['page']}, {x['status']} : {x['reason']}) "
                        f"« {one_line(x['quote'], 120)} »")
        elif f["status"] == NORM_REF:
            ref = next(x for x in f["findings"] if x["status"] == NORM_REF)
            say(f"  Le document renvoie à {ref['norm']} sans écrire la valeur (p. {ref['page']}) "
                f"« {one_line(ref['quote'], 200)} »")
            alert("  Laissé vide, le champ est hérité de la norme : exigence du client si le renvoi est confirmé à "
                  "la fin de la relecture, sinon recommandation plafonnée à mineur.")
        else:
            say(f"  Statut : {f['status']}")
            for k, x in enumerate(f["findings"], start=1):
                mark = f"[{k}] " if x in candidates else "    "
                line = (f"  {mark}{scalar(x['value'])} (p. {x['page']}, {x['status']}"
                        f"{' : ' + x['reason'] if x.get('reason') else ''}) « {one_line(x['quote'], 160)} »")
                (alert if x["status"] == IMPLAUSIBLE else say)(line)
        base_value = _get(base_raw, path)
        say(f"  Profil de base ({review.base.name}) : {scalar(base_value) if base_value is not None else '—'}")
        if path in norms:
            say(f"  Norme (information) : {scalar(norms[path][0])} ({norms[path][1]})")
        choices = (["a"] if f["status"] in (OK, IMPLAUSIBLE) else []) + [str(k) for k in range(1, len(f["findings"]) + 1)
                                                          if f["findings"][k - 1] in candidates]
        choices += ["c", "v"] + (["g"] if base_value is not None else [])
        labels = {"a": "accepter", "c": "corriger", "v": "laisser vide", "g": "garder la valeur de base"}
        menu = " ".join(f"[{c}] {labels.get(c, 'choisir ce candidat')}" for c in choices)
        # An implausible value is never accepted by default.
        default = "a" if f["status"] == OK else "g" if "g" in choices else "v"
        while True:
            answer = ask(f"  {menu} (Entrée = {default})").strip().lower() or default
            if answer in choices:
                break
            say(f"  Réponse attendue : {', '.join(choices)}")
        if answer == "a":
            first = next(x for x in good if x["value"] == f["value"] and x["status"] == f["status"])
            review.decisions.append(Decision(path, "accept", f["value"], _citation(doc, first)))
        elif answer.isdigit():
            x = f["findings"][int(answer) - 1]
            review.decisions.append(Decision(path, "accept", x["value"], _citation(doc, x)))
        elif answer == "v":
            review.decisions.append(Decision(path, "empty"))
        elif answer == "g":
            review.decisions.append(Decision(path, "keep"))
        else:
            review.decisions.append(_correct(path, specs.get(path), doc, ask, say))
            learn(review.glossary, path, ask, say)
    return skipped


def ask_references(review: Review, ask: Ask, say: Say, alert: Say | None = None) -> None:
    """Confirm, one by one, the references of the document to a norm of normes/ (meta.refers_to)."""
    alert = alert or say
    norms_dir = norms_dir_for(review.base)
    doc = review.meta.get("source_document", "document")
    extends = review.meta.get("extends", [])
    cited = [n for n in review.cited_norms if n.get("available") and n["norm"] in extends and n["norm"] != HOUSE]
    for i, n in enumerate(cited, start=1):
        norm = load_norm(norms_dir / f"{n['norm']}.yaml")
        title = norm.meta.document.title.split(" — ")[0]
        say(f"\n[renvoi {i}/{len(cited)}] Le document renvoie à {title} (p. {n['page']}) « {one_line(n['quote'], 200)} »")
        values = leaves({k: v for k, v in norm.raw.items() if k != "sources"})
        say("  Valeurs de la norme : " + "; ".join(f"{p} = {one_line(scalar(v), 60)}" for p, v in values))
        alert("  Confirmé, ces valeurs deviennent des exigences du client (sans plafonnement), sauf celles que le "
              "client chiffre lui-même. Non confirmé, ce sont des recommandations plafonnées à mineur.")
        answer = ask(f"  Confirmer le renvoi à {title} ? [o/N]").strip().lower()
        if answer in ("o", "oui", "y", "yes"):
            review.references.append({"norm": n["norm"], "source": f"{doc} p. {n['page']} : « {one_line(n['quote'], 300)} »"})


def learn(g: glossary_mod.Glossary | None, path: str, ask: Ask, say: Say) -> None:
    """Offer to add the broadcaster's term for ``path`` to the glossary, after confirmation."""
    if g is None:
        return
    term = " ".join(ask("  Terme employé par le document pour ce champ, à ajouter au glossaire "
                        "(Entrée : aucun)").split())
    if not term:
        return
    if g.has_term(path, term):
        say("  Ce terme est déjà reconnu par le glossaire.")
        return
    answer = ask(f"  Ajouter « {term} » au glossaire pour {path} ? [f] terme français [e] terme anglais "
                 "[n] non (Entrée = n)").strip().lower()
    if answer in ("f", "e") and glossary_mod.add_term(g, path, "fr" if answer == "f" else "en", term):
        say(f"  Ajouté à {g.path.name if g.path else 'glossaire'} ({path}). Le glossaire reste à relire par un humain.")


def _correct(path: str, spec, doc: str, ask: Ask, say: Say) -> Decision:
    while True:
        text = ask("  Valeur (YAML, ex. -23 ou [\"25/1\"])")
        try:
            value = yaml.safe_load(text)
        except yaml.YAMLError:
            say("  Valeur illisible.")
            continue
        checked, why = check_value(spec, value) if spec else (value, None)
        if why:
            say(f"  {why}")
            continue
        break
    page = ask("  Page du document (vide si aucune)").strip()
    quote = ask("  Citation exacte du document (vide si aucune)").strip()
    if page and quote:
        source = f"{doc} p. {page} : « {quote} » (corrigé à la relecture)"
    else:
        source = f"A VERIFIER : valeur saisie à la relecture, sans citation de {doc}"
    return Decision(path, "correct", checked, source)


def build(review: Review) -> tuple[dict[str, Any], dict[str, str]]:
    """(profile data, comments) from the base profile and the decisions."""
    base = read_yaml(review.base)
    meta_key = "profile" if "profile" in base and "meta" not in base else "meta"
    base_meta = base.pop(meta_key, {}) or {}
    sources: dict[str, str] = dict(base.pop("sources", None) or {})
    data = copy.deepcopy(base)
    for d in review.decisions:
        if d.action in ("accept", "correct"):
            _set(data, d.path, d.value)
            sources[d.path] = d.source
        elif d.action == "empty":
            _delete(data, d.path)
            sources.pop(d.path, None)
    m = review.meta
    meta = {"name": m["name"], "version": base_meta.get("version", m.get("version", "1.0")),
            "broadcaster": base_meta.get("broadcaster", m.get("broadcaster")), "source_document": m["source_document"],
            "notes": f"Profil relu champ par champ depuis le brouillon {review.draft.name}.",
            "extends": m.get("extends", []), "refers_to": _references(base_meta, review),
            "status": "validated", "validated_by": None, "validated_at": None,
            "source_pdf": m.get("source_pdf"), "source_pdf_sha256": m.get("source_pdf_sha256")}
    data = {"meta": meta, **data, "sources": dict(sorted(sources.items()))}
    cited = set(sources)
    comments = {}
    for path, _ in leaves({k: v for k, v in data.items() if k not in ("meta", "sources")}):
        if not any(path == c or path.startswith(c + ".") for c in cited) and not path.startswith("rules.severity."):
            comments[path] = f"A VERIFIER : sans citation de {m['source_document']} (valeur de {review.base.name})"
    return data, comments


def _references(base_meta: dict[str, Any], review: Review) -> list[dict]:
    """References of the base profile, then those confirmed now (one per norm), for norms of extends."""
    extends = review.meta.get("extends", [])
    out = {r["norm"]: r for r in base_meta.get("refers_to") or [] if isinstance(r, dict) and "norm" in r}
    out.update({r["norm"]: r for r in review.references})
    return [r for r in out.values() if r["norm"] in extends]


_MISSING = re.compile(r"champ obligatoire manquant « ([\w.]+) »")


def missing_fields(error: ReviewError) -> list[str]:
    return _MISSING.findall(str(error))


def complete(data: dict[str, Any], comments: dict[str, str], missing: list[str], doc: str, ask: Ask,
             say: Say, glossary: glossary_mod.Glossary | None = None) -> None:
    """Ask for each required field left missing (a section accepted only in part, e.g. format.delivery
    with its codec only). An empty answer removes the incomplete section instead."""
    specs = {s.path: s for s in catalogue()}
    for path in missing:
        parent = path.rsplit(".", 1)[0]
        if _get(data, parent) is None:
            continue  # already removed with another missing field of the same section
        spec = specs.get(path)
        say(f"\nChamp obligatoire manquant : {path}" + (f" — {spec.description}" if spec else ""))
        while True:
            text = ask(f"  Valeur (YAML), ou Entrée pour retirer toute la section {parent}").strip()
            if not text:
                _delete(data, parent)
                data["sources"] = {k: v for k, v in data["sources"].items() if not k.startswith(parent + ".")}
                break
            value, why = (check_value(spec, yaml.safe_load(text)) if spec else (yaml.safe_load(text), None))
            if why:
                say(f"  {why}")
                continue
            _set(data, path, value)
            comments[path] = f"A VERIFIER : valeur saisie à la relecture, sans citation de {doc}"
            learn(glossary, path, ask, say)
            break


def norm_only_rules(resolved: ResolvedProfile) -> list[str]:
    """Blocking or major rules whose value would come from an international norm only (capped at minor):
    not from the client, not from a norm the client refers to."""
    capped = capped_norm_values(resolved)
    out = []
    for event_type, chain in resolved.profile.rules.severity.items():
        levels = [r.severity for r in chain if r.severity in ("blocking", "major")]
        if not levels:
            continue
        probe = Draft(type=event_type, title="", source="", scope="file", frame_start=0, frame_end=0,
                      value_text="", threshold_text="")
        deps = {d for kind in ("long", "short") for d in depends_on(probe, kind)}
        hits = sorted({p for p in capped for d in deps if p == d or p.startswith(d + ".")})
        if hits:
            files = sorted({resolved.origins[p].file for p in hits})
            worst = "blocking" if "blocking" in levels else "major"
            out.append(f"rules.severity.{event_type} ({worst}) : {', '.join(hits)} vien(nen)t seulement de "
                       f"{', '.join(files)} → plafonné à minor")
    return out


def write(review: Review, out: Path, data: dict[str, Any], comments: dict[str, str]) -> tuple[ResolvedProfile, Path]:
    """Check the profile (written next to ``out`` so that its norms are found), then move it in place."""
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.name}.relecture.tmp")
    header = [f"Profil {data['meta']['name']} relu avec pad-guard review-profile depuis {review.draft.name}.",
              f"Document : {data['meta']['source_pdf']} (SHA-256 {data['meta']['source_pdf_sha256']}).",
              "Chaque valeur citée a sa source dans la section « sources » ; « A VERIFIER » : valeur sans citation",
              "du document du client (CLAUDE.md, principe 2)."]
    tmp.write_text(dump(data, comments, header), encoding="utf-8", newline="\n")
    try:
        resolved = resolve_profile(tmp)
    except ProfileError as exc:
        tmp.unlink(missing_ok=True)
        raise ReviewError("profil incomplet ou invalide, rien n'a été écrit :\n  - " + "\n  - ".join(exc.messages)) from None
    return resolved, tmp


def finish(tmp: Path, out: Path) -> None:
    os.replace(tmp, out)


def save_answers(review: Review) -> Path:
    path = review.draft.with_name(review.draft.stem + ".review.json")
    data = {"decisions": [vars(d) for d in review.decisions], "references": review.references}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    return path


def validate(data: dict[str, Any], who: str) -> None:
    data["meta"]["validated_by"] = who
    data["meta"]["validated_at"] = dt.date.today().isoformat()
