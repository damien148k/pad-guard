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
CHOICE_LABELS = {"a": "accepter", "c": "corriger", "v": "laisser vide", "g": "garder la valeur de base"}


@dataclass
class Question:
    """What the reviewer must decide about one field: shared by the CLI and the web interface."""

    path: str
    description: str
    status: str  # A_VERIFIER | CONFLIT | INVRAISEMBLABLE | RENVOI_NORME | other (with everything)
    value: Any  # proposed value (A_VERIFIER, INVRAISEMBLABLE)
    findings: list[dict]  # all the proposals of the model, in order (candidate k = findings[k - 1])
    proposal: dict | None  # the finding behind the proposed value (A_VERIFIER, INVRAISEMBLABLE)
    reference: dict | None  # the finding of a reference to a norm (RENVOI_NORME)
    rejected: list[dict]  # refused proposals with another value: the proposed value may be incomplete
    candidates: list[int]  # numbers (from 1) of the findings that may be chosen (CONFLIT)
    base_value: Any  # value of the base profile (None: absent)
    norm: tuple[Any, str] | None  # (value, norm title), for information
    choices: list[str]  # "a", candidate numbers, "c", "v", "g"
    default: str  # CLI default (an implausible value is never accepted by default)

    @property
    def implausible(self) -> bool:
        return self.status == IMPLAUSIBLE


@dataclass
class ReferenceQuestion:
    """A reference of the document to a norm of normes/, to confirm or not (meta.refers_to)."""

    norm: str
    title: str
    page: int
    quote: str
    values: list[tuple[str, Any]]


def questions(review: Review, everything: bool = False) -> tuple[list[Question], list[dict]]:
    """(questions, fields not asked about) for the fields to verify (A_VERIFIER, INVRAISEMBLABLE,
    RENVOI_NORME) and in conflict; with ``everything``, also the fields whose proposals were all
    refused. The fields not asked about keep the value of the base profile."""
    base_raw = read_yaml(review.base)
    norms = norm_values(review.meta.get("extends", []), norms_dir_for(review.base))
    asked = [f for f in review.fields if everything or f["status"] in ASKED]
    skipped = [f for f in review.fields if f not in asked]
    out = []
    for f in asked:
        good = [x for x in f["findings"] if x["status"] in (OK, CONFLICT, IMPLAUSIBLE)]
        proposal = reference = None
        rejected: list[dict] = []
        if f["status"] in (OK, IMPLAUSIBLE):
            proposal = next(x for x in good if x["value"] == f["value"] and x["status"] == f["status"])
            rejected = [x for x in f["findings"] if x["status"] not in (OK, IMPLAUSIBLE, NORM_REF)
                        and x["value"] is not None and x["value"] != f["value"]]
        elif f["status"] == NORM_REF:
            reference = next(x for x in f["findings"] if x["status"] == NORM_REF)
        candidates = ([k for k, x in enumerate(f["findings"], start=1) if x in good]
                      if f["status"] == CONFLICT else [])
        base_value = _get(base_raw, f["path"])
        choices = (["a"] if proposal else []) + [str(k) for k in candidates]
        choices += ["c", "v"] + (["g"] if base_value is not None else [])
        default = "a" if f["status"] == OK else "g" if "g" in choices else "v"
        out.append(Question(path=f["path"], description=f["description"], status=f["status"], value=f["value"],
                            findings=f["findings"], proposal=proposal, reference=reference, rejected=rejected,
                            candidates=candidates, base_value=base_value, norm=norms.get(f["path"]),
                            choices=choices, default=default))
    return out, skipped


def decide(review: Review, q: Question, answer: str, correction: Decision | None = None) -> Decision:
    """Record the decision ``answer`` (one of ``q.choices``) about ``q``; "c" takes ``correction``
    (see ``corrected``). A new decision about the same field replaces the previous one."""
    if answer not in q.choices:
        raise ReviewError(f"{q.path} : réponse attendue parmi {', '.join(q.choices)}")
    doc = review.meta.get("source_document", "document")
    if answer == "a":
        d = Decision(q.path, "accept", q.value, _citation(doc, q.proposal))
    elif answer.isdigit():
        x = q.findings[int(answer) - 1]
        d = Decision(q.path, "accept", x["value"], _citation(doc, x))
    elif answer == "v":
        d = Decision(q.path, "empty")
    elif answer == "g":
        d = Decision(q.path, "keep")
    else:
        if correction is None or correction.path != q.path:
            raise ReviewError(f"{q.path} : la correction n'a pas de valeur")
        d = correction
    review.decisions = [x for x in review.decisions if x.path != q.path] + [d]
    return d


def corrected(review: Review, path: str, value: Any, page: str = "", quote: str = "") -> Decision:
    """The correction of ``path`` by the reviewer; ReviewError if the value is not acceptable."""
    spec = {s.path: s for s in catalogue()}.get(path)
    checked, why = check_value(spec, value) if spec else (value, None)
    if why:
        raise ReviewError(why)
    doc = review.meta.get("source_document", "document")
    page, quote = str(page).strip(), quote.strip()
    if page and quote:
        source = f"{doc} p. {page} : « {quote} » (corrigé à la relecture)"
    else:
        source = f"A VERIFIER : valeur saisie à la relecture, sans citation de {doc}"
    return Decision(path, "correct", checked, source)


def ask_fields(review: Review, ask: Ask, say: Say, everything: bool = False, alert: Say | None = None) -> list[dict]:
    """Ask, in the terminal, about the fields of ``questions``. Returns the fields not asked about.
    ``alert`` prints in red."""
    alert = alert or say
    for n in review.capped_pages:
        alert(f"Page {n} : {CAPPED} (relire cette page du document à la main).")
    asked, skipped = questions(review, everything)
    total = len(asked)
    for i, q in enumerate(asked, start=1):
        say(f"\n[{i}/{total}] {q.path} — {q.description}")
        if q.proposal:
            first = q.proposal
            say(f"  Proposé : {scalar(q.value)} (p. {first['page']}) « {one_line(first['quote'], 200)} »")
            if q.implausible:
                alert(f"  INVRAISEMBLABLE : {first['reason']}")
            if q.rejected:
                alert(f"  {len(q.rejected)} autre(s) proposition(s) rejetée(s) avec une autre valeur : "
                      "la valeur proposée est peut-être incomplète")
                for x in q.rejected:
                    say(f"      {one_line(scalar(x['value']), 120)} (p. {x['page']}, {x['status']} : {x['reason']}) "
                        f"« {one_line(x['quote'], 120)} »")
        elif q.reference:
            ref = q.reference
            say(f"  Le document renvoie à {ref['norm']} sans écrire la valeur (p. {ref['page']}) "
                f"« {one_line(ref['quote'], 200)} »")
            alert("  Laissé vide, le champ est hérité de la norme : exigence du client si le renvoi est confirmé à "
                  "la fin de la relecture, sinon recommandation plafonnée à mineur.")
        else:
            say(f"  Statut : {q.status}")
            for k, x in enumerate(q.findings, start=1):
                mark = f"[{k}] " if k in q.candidates else "    "
                line = (f"  {mark}{scalar(x['value'])} (p. {x['page']}, {x['status']}"
                        f"{' : ' + x['reason'] if x.get('reason') else ''}) « {one_line(x['quote'], 160)} »")
                (alert if x["status"] == IMPLAUSIBLE else say)(line)
        say(f"  Profil de base ({review.base.name}) : {scalar(q.base_value) if q.base_value is not None else '—'}")
        if q.norm:
            say(f"  Norme (information) : {scalar(q.norm[0])} ({q.norm[1]})")
        menu = " ".join(f"[{c}] {CHOICE_LABELS.get(c, 'choisir ce candidat')}" for c in q.choices)
        while True:
            answer = ask(f"  {menu} (Entrée = {q.default})").strip().lower() or q.default
            if answer in q.choices:
                break
            say(f"  Réponse attendue : {', '.join(q.choices)}")
        correction = _correct(review, q.path, ask, say) if answer == "c" else None
        decide(review, q, answer, correction)
        if answer == "c":
            learn(review.glossary, q.path, ask, say)
    return skipped


def reference_questions(review: Review) -> list[ReferenceQuestion]:
    """The references of the document to a norm of normes/ cited in extends (not the house rules)."""
    norms_dir = norms_dir_for(review.base)
    extends = review.meta.get("extends", [])
    out = []
    for n in review.cited_norms:
        if not (n.get("available") and n["norm"] in extends and n["norm"] != HOUSE):
            continue
        norm = load_norm(norms_dir / f"{n['norm']}.yaml")
        out.append(ReferenceQuestion(norm=n["norm"], title=norm.meta.document.title.split(" — ")[0], page=n["page"],
                                     quote=n["quote"],
                                     values=leaves({k: v for k, v in norm.raw.items() if k != "sources"})))
    return out


def confirm_reference(review: Review, rq: ReferenceQuestion, confirmed: bool) -> None:
    """Confirm (or withdraw) a reference: confirmed, it goes to meta.refers_to."""
    doc = review.meta.get("source_document", "document")
    review.references = [r for r in review.references if r["norm"] != rq.norm]
    if confirmed:
        review.references.append({"norm": rq.norm, "source": f"{doc} p. {rq.page} : « {one_line(rq.quote, 300)} »"})


def ask_references(review: Review, ask: Ask, say: Say, alert: Say | None = None) -> None:
    """Confirm, one by one, the references of the document to a norm of normes/ (meta.refers_to)."""
    alert = alert or say
    cited = reference_questions(review)
    for i, rq in enumerate(cited, start=1):
        say(f"\n[renvoi {i}/{len(cited)}] Le document renvoie à {rq.title} (p. {rq.page}) « {one_line(rq.quote, 200)} »")
        say("  Valeurs de la norme : " + "; ".join(f"{p} = {one_line(scalar(v), 60)}" for p, v in rq.values))
        alert("  Confirmé, ces valeurs deviennent des exigences du client (sans plafonnement), sauf celles que le "
              "client chiffre lui-même. Non confirmé, ce sont des recommandations plafonnées à mineur.")
        answer = ask(f"  Confirmer le renvoi à {rq.title} ? [o/N]").strip().lower()
        if answer in ("o", "oui", "y", "yes"):
            confirm_reference(review, rq, True)


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


def _correct(review: Review, path: str, ask: Ask, say: Say) -> Decision:
    while True:
        text = ask("  Valeur (YAML, ex. -23 ou [\"25/1\"])")
        try:
            value = yaml.safe_load(text)
        except yaml.YAMLError:
            say("  Valeur illisible.")
            continue
        try:
            corrected(review, path, value)
        except ReviewError as exc:
            say(f"  {exc}")
            continue
        break
    page = ask("  Page du document (vide si aucune)").strip()
    quote = ask("  Citation exacte du document (vide si aucune)").strip()
    return corrected(review, path, value, page, quote)


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


def missing_section(data: dict[str, Any], path: str) -> str | None:
    """The section of a missing required field, None if already removed with another field of it."""
    parent = path.rsplit(".", 1)[0]
    return parent if _get(data, parent) is not None else None


def fill_missing(data: dict[str, Any], comments: dict[str, str], path: str, value: Any, doc: str) -> None:
    """Set the required field ``path`` left missing (ReviewError if the value is not acceptable), or,
    with ``value`` None, remove its incomplete section."""
    parent = path.rsplit(".", 1)[0]
    if value is None:
        _delete(data, parent)
        data["sources"] = {k: v for k, v in data["sources"].items() if not k.startswith(parent + ".")}
        return
    spec = {s.path: s for s in catalogue()}.get(path)
    checked, why = check_value(spec, value) if spec else (value, None)
    if why:
        raise ReviewError(why)
    _set(data, path, checked)
    comments[path] = f"A VERIFIER : valeur saisie à la relecture, sans citation de {doc}"


def complete(data: dict[str, Any], comments: dict[str, str], missing: list[str], doc: str, ask: Ask,
             say: Say, glossary: glossary_mod.Glossary | None = None) -> None:
    """Ask for each required field left missing (a section accepted only in part, e.g. format.delivery
    with its codec only). An empty answer removes the incomplete section instead."""
    specs = {s.path: s for s in catalogue()}
    for path in missing:
        parent = missing_section(data, path)
        if parent is None:
            continue  # already removed with another missing field of the same section
        spec = specs.get(path)
        say(f"\nChamp obligatoire manquant : {path}" + (f" — {spec.description}" if spec else ""))
        while True:
            text = ask(f"  Valeur (YAML), ou Entrée pour retirer toute la section {parent}").strip()
            try:
                fill_missing(data, comments, path, yaml.safe_load(text) if text else None, doc)
            except ReviewError as exc:
                say(f"  {exc}")
                continue
            if text:
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
