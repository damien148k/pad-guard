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
from pad_guard.draft import pdf as pdf_mod
from pad_guard.draft import verify
from pad_guard.draft.extract import CONFLICT, IMPLAUSIBLE, NORM_REF, OK
from pad_guard.draft.schema import catalogue, check_value
from pad_guard.draft.write import CAPPED, dump, one_line, scalar
from pad_guard.profiles.resolve import (
    HOUSE,
    NORMS_DIR,
    REPO_NORMS,
    ResolvedProfile,
    _norm_chain,
    capped_norm_values,
    is_norm,
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
    base: Path | None  # None for a norm: partial, no base profile
    decisions: list[Decision] = field(default_factory=list)
    glossary: glossary_mod.Glossary | None = None
    cited_norms: list[dict] = field(default_factory=list)  # findings.json "cited_norms"
    capped_pages: list[int] = field(default_factory=list)  # findings.json "capped_pages"
    references: list[dict] = field(default_factory=list)  # confirmed: {norm, source} for meta.refers_to
    norms_dir: Path | None = None  # norms of a norm draft (normes/ above normes/drafts/)
    # A second review of a norm already validated (normes/<name>.yaml): its values are the base, kept
    # unless decided otherwise, like the base profile of a profile.
    norm_base: Path | None = None

    @property
    def is_norm(self) -> bool:
        return self.meta.get("kind") == "norm"

    @property
    def norms(self) -> Path:
        return self.norms_dir if self.base is None else norms_dir_for(self.base)

    @property
    def doc(self) -> str:
        """The document as cited in a source: « CST-RT-040 V1.2, 2016 » for a norm, else the client's file name."""
        if self.is_norm:
            d = self.meta["document"]
            return f"{d['title'].split(' — ')[0]} {d['version']}"
        return self.meta.get("source_document", "document")


def load(draft: Path, base: Path | None) -> Review:
    sidecar = draft.with_name(draft.stem + ".findings.json")
    if not sidecar.is_file():
        raise ReviewError(f"{sidecar.name} absent à côté de {draft} : relancer « draft-profile »")
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    meta = data["meta"]
    norms_dir = None
    if meta.get("kind") == "norm":
        if base is not None:
            raise ReviewError("une norme n'a pas de profil de base (--base) : ses valeurs viennent de son seul document")
        norms_dir = next((d for d in draft.resolve().parents if d.name == NORMS_DIR), REPO_NORMS)
    elif base is None:
        own = ROOT / "profiles" / f"{meta['name']}.yaml"
        base = own if own.is_file() else TEMPLATE
    terms = (norms_dir or norms_dir_for(base)) / glossary_mod.GLOSSARY.name
    try:
        g = glossary_mod.load(terms) if terms.is_file() else None
    except glossary_mod.GlossaryError as exc:
        raise ReviewError(str(exc)) from None
    norm_base = norms_dir / f"{meta['name']}.yaml" if norms_dir is not None else None
    return Review(draft=draft, meta=meta, fields=data["fields"], base=base, glossary=g,
                  cited_norms=data.get("cited_norms", []), capped_pages=data.get("capped_pages", []),
                  norms_dir=norms_dir, norm_base=norm_base if norm_base is not None and norm_base.is_file() else None)


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
    page: int  # the citation proposed (the first of ``candidates``)
    quote: str
    values: list[tuple[str, Any]]
    # model: proposed by the model (RENVOI_NORME) ; alias: an alias of the glossary found in the text of
    # the PDF, every line naming the norm is a candidate citation ; manual: given by the reviewer.
    found_by: str = "model"
    candidates: list[tuple[int, str]] = field(default_factory=list)  # (page, line), alias only


def questions(review: Review, everything: bool = False) -> tuple[list[Question], list[dict]]:
    """(questions, fields not asked about) for the fields to verify (A_VERIFIER, INVRAISEMBLABLE,
    RENVOI_NORME) and in conflict; with ``everything``, also the fields whose proposals were all
    refused. The fields not asked about keep the value of the base profile."""
    base_raw = read_yaml(review.base or review.norm_base) if (review.base or review.norm_base) else {}
    norms = norm_values(review.meta.get("extends", []), review.norms)
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
    doc = review.doc
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


def corrected(review: Review, path: str, value: Any, page: str = "", quote: str = "",
              check_only: bool = False) -> Decision:
    """The correction of ``path`` by the reviewer; ReviewError if the value is not acceptable. A value
    of a norm always cites its document (page and quote), unless ``check_only`` (the value alone)."""
    spec = {s.path: s for s in catalogue()}.get(path)
    checked, why = check_value(spec, value) if spec else (value, None)
    if why:
        raise ReviewError(why)
    doc = review.doc
    page, quote = str(page).strip(), quote.strip()
    if review.is_norm and not check_only and not (page and quote):
        raise ReviewError("valeur d'une norme : la page et la citation exacte du document sont obligatoires")
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
        if review.base is not None or review.norm_base is not None:
            which = f"Profil de base ({review.base.name})" if review.base else f"Norme actuelle ({review.norm_base.name})"
            say(f"  {which} : {scalar(q.base_value) if q.base_value is not None else '—'}")
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


def _referable(review: Review, name: str) -> bool:
    """A norm of normes/ a reference may point to: not the house rules, not the norm under review."""
    return name not in (HOUSE, review.meta["name"]) and (review.norms / f"{name}.yaml").is_file() \
        and is_norm(read_yaml(review.norms / f"{name}.yaml"))


def _question(review: Review, name: str, page: int, quote: str, found_by: str = "model",
              candidates: list[tuple[int, str]] | None = None) -> ReferenceQuestion:
    norm = load_norm(review.norms / f"{name}.yaml")
    return ReferenceQuestion(norm=name, title=norm.meta.document.title.split(" — ")[0], page=page, quote=quote,
                             values=leaves({k: v for k, v in norm.raw.items() if k != "sources"}),
                             found_by=found_by, candidates=candidates or [])


def document(review: Review) -> pdf_mod.Document | None:
    """The PDF of the draft, when it is still where draft-profile read it, unchanged."""
    if not hasattr(review, "_document"):
        path = Path(review.meta.get("source_pdf") or "")
        path = path if path.is_absolute() else ROOT / path
        doc = None
        if path.is_file():
            try:
                doc = pdf_mod.read(path)
            except pdf_mod.PdfError:
                doc = None
        sha = review.meta.get("source_pdf_sha256")
        review._document = doc if doc is not None and (sha is None or doc.sha256 == sha) else None
    return review._document


def _clean(line: str) -> str:
    """A line of the PDF as a citation: spaces collapsed, list bullets of symbol fonts (private use area,
    e.g. U+F0D8) removed."""
    return " ".join("".join(c for c in line if not "" <= c <= "").split())


def reference_questions(review: Review) -> list[ReferenceQuestion]:
    """The references of the document to a norm of normes/: proposed by the model (cited in extends),
    then found in the text of the PDF by an alias of the glossary (deterministic, every line naming
    the norm is a candidate citation). Never the house rules."""
    extends = review.meta.get("extends", [])
    done = {r["norm"] for r in (read_yaml(review.norm_base)["meta"].get("refers_to") or [])} if review.norm_base else set()
    out = [_question(review, n["norm"], n["page"], n["quote"]) for n in review.cited_norms
           if n.get("available") and n["norm"] in extends and n["norm"] not in done and _referable(review, n["norm"])]
    doc = document(review)
    if doc is None or review.glossary is None:
        return out
    seen = {q.norm for q in out} | done  # a reference of the norm already validated is not asked again
    found: dict[str, list[tuple[int, str]]] = {}
    for page in doc.pages:
        for line in page.text.splitlines():
            for key in review.glossary.norms_in(line):
                if key not in seen and _referable(review, key):
                    found.setdefault(key, []).append((page.number, _clean(line)))
    for key, lines in found.items():
        out.append(_question(review, key, lines[0][0], lines[0][1], "alias", lines))
    return out


def manual_reference(review: Review, name: str, page: str, quote: str) -> ReferenceQuestion:
    """A reference the model and the aliases missed, given by the reviewer: the quote must be in its page
    of the PDF and name the norm (an alias of the glossary). ReviewError otherwise."""
    name, quote = name.strip(), " ".join(quote.split())
    if not _referable(review, name):
        raise ReviewError(f"« {name} » n'est pas une norme de normes/ (nom du fichier sans .yaml, pas {HOUSE})")
    doc = document(review)
    if doc is None:
        raise ReviewError("PDF du brouillon introuvable ou modifié : la citation ne peut pas être vérifiée")
    found = doc.page(int(page)) if page.strip().isdigit() else None
    if found is None:
        raise ReviewError(f"page {page} absente du document ({len(doc.pages)} pages)")
    if not quote or not verify.quote_in(quote, found.full_text):
        raise ReviewError(f"citation introuvable p. {found.number}")
    if review.glossary is None or name not in review.glossary.norms_in(quote):
        raise ReviewError(f"la citation ne nomme pas {name} (alias du glossaire normes/glossaire.yaml)")
    return _question(review, name, found.number, quote, "manual")


def confirm_reference(review: Review, rq: ReferenceQuestion, confirmed: bool, cited_version: str = "",
                      choice: int = 0) -> None:
    """Confirm (or withdraw) a reference: confirmed, it goes to meta.refers_to, with the version the
    document cites when it is not the one of normes/ ; ``choice``: the candidate citation (alias)."""
    review.references = [r for r in review.references if r["norm"] != rq.norm]
    if confirmed:
        page, quote = rq.candidates[choice] if rq.candidates else (rq.page, rq.quote)
        ref = {"norm": rq.norm, "source": f"{review.doc} p. {page} : « {one_line(quote, 300)} »"}
        if cited_version.strip():
            ref["cited_version"] = cited_version.strip()
        review.references.append(ref)


YES = ("o", "oui", "y", "yes")


def _ask_one(review: Review, rq: ReferenceQuestion, ask: Ask, say: Say, alert: Say) -> None:
    say("  Valeurs de la norme : " + "; ".join(f"{p} = {one_line(scalar(v), 60)}" for p, v in rq.values))
    name = review.meta["name"]
    if review.is_norm:
        alert(f"  Confirmé, {name} étend {rq.title} sans recopier ses valeurs : quand un client renvoie à {name}, "
              f"ces valeurs deviennent ses exigences, sauf celles que {name} écrit elle-même. Non confirmé, "
              f"{rq.title} n'est pas étendue.")
    else:
        alert("  Confirmé, ces valeurs deviennent des exigences du client (sans plafonnement), sauf celles que le "
              "client chiffre lui-même. Non confirmé, ce sont des recommandations plafonnées à mineur.")
    choice = 0
    if len(rq.candidates) > 1:
        while True:
            answer = ask(f"  Citation du renvoi : numéro 1 à {len(rq.candidates)} (Entrée : pas de renvoi)").strip()
            if not answer or (answer.isdigit() and 1 <= int(answer) <= len(rq.candidates)):
                break
            say(f"  Réponse attendue : un numéro de 1 à {len(rq.candidates)}, ou Entrée")
        if not answer:
            return
        choice = int(answer) - 1
    elif ask(f"  Confirmer le renvoi à {rq.title} ? [o/N]").strip().lower() not in YES:
        return
    version = ""
    if review.is_norm:
        applied = load_norm(review.norms / f"{rq.norm}.yaml").meta.document.version
        version = ask(f"  Version citée par le document, si ce n'est pas {applied} (Entrée : la même)")
    confirm_reference(review, rq, True, version, choice)


def ask_references(review: Review, ask: Ask, say: Say, alert: Say | None = None) -> None:
    """Confirm, one by one, the references of the document to a norm of normes/ (meta.refers_to): those
    the model proposed, those an alias of the glossary finds in the PDF, then those the reviewer adds."""
    alert = alert or say
    cited = reference_questions(review)
    for i, rq in enumerate(cited, start=1):
        if rq.found_by == "alias":
            say(f"\n[renvoi {i}/{len(cited)}] {rq.title} est nommée dans le document (alias du glossaire, non "
                "proposé par le modèle) :")
            for k, (page, line) in enumerate(rq.candidates, start=1):
                say(f"  [{k}] p. {page} « {one_line(line, 160)} »")
        else:
            say(f"\n[renvoi {i}/{len(cited)}] Le document renvoie à {rq.title} (p. {rq.page}) "
                f"« {one_line(rq.quote, 200)} »")
        _ask_one(review, rq, ask, say, alert)
    while True:
        name = ask("\nAutre renvoi non détecté ? Nom de la norme dans normes/ (Entrée : aucun)").strip()
        if not name:
            return
        page = ask("  Page du document").strip()
        quote = ask("  Citation exacte du renvoi").strip()
        try:
            rq = manual_reference(review, name, page, quote)
        except ReviewError as exc:
            say(f"  {exc}")
            continue
        _ask_one(review, rq, ask, say, alert)


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
            corrected(review, path, value, check_only=True)
        except ReviewError as exc:
            say(f"  {exc}")
            continue
        break
    optional = "" if review.is_norm else " (vide si aucune)"
    while True:
        page = ask(f"  Page du document{optional}").strip()
        quote = ask(f"  Citation exacte du document{optional}").strip()
        try:
            return corrected(review, path, value, page, quote)
        except ReviewError as exc:
            say(f"  {exc}")


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
            "extends": with_references(m.get("extends", []), review.references),
            "refers_to": _references(base_meta, review),
            "status": "validated", "validated_by": None, "validated_at": None,
            "source_pdf": m.get("source_pdf"), "source_pdf_sha256": m.get("source_pdf_sha256")}
    data = {"meta": meta, **data, "sources": dict(sorted(sources.items()))}
    cited = set(sources)
    comments = {}
    for path, _ in leaves({k: v for k, v in data.items() if k not in ("meta", "sources")}):
        if not any(path == c or path.startswith(c + ".") for c in cited) and not path.startswith("rules.severity."):
            comments[path] = f"A VERIFIER : sans citation de {m['source_document']} (valeur de {review.base.name})"
    return data, comments


def with_references(extends: list[str], references: list[dict]) -> list[str]:
    """``extends`` with the norms of the confirmed references it lacks (found by an alias or given by the
    reviewer), before the house rules: the later the layer, the higher its priority."""
    missing = [r["norm"] for r in references if r["norm"] not in extends]
    if HOUSE in extends:
        i = extends.index(HOUSE)
        return extends[:i] + missing + extends[i:]
    return extends + missing


def _references(base_meta: dict[str, Any], review: Review) -> list[dict]:
    """References of the base profile, then those confirmed now (one per norm), for norms of extends."""
    extends = with_references(review.meta.get("extends", []), review.references)
    out = {r["norm"]: r for r in base_meta.get("refers_to") or [] if isinstance(r, dict) and "norm" in r}
    out.update({r["norm"]: r for r in review.references})
    return [r for r in out.values() if r["norm"] in extends]


def build_norm(review: Review) -> dict[str, Any]:
    """The norm from the decisions alone: a partial profile, every value with its citation; it
    extends only the norms whose reference was confirmed (no value copied). For a second review of a
    validated norm, its values, sources and references are the base: kept unless decided otherwise."""
    if review.norm_base is not None:
        return _completed_norm(review)
    data: dict[str, Any] = {}
    sources: dict[str, str] = {}
    for d in review.decisions:
        if d.action in ("accept", "correct"):
            _set(data, d.path, d.value)
            sources[d.path] = d.source
    m = review.meta
    confirmed = {r["norm"] for r in review.references}
    extends = [n for n in with_references(m.get("extends", []), review.references) if n in confirmed]
    meta = {"kind": "norm", "name": m["name"], "document": dict(m["document"]), "source_pdf": m.get("source_pdf"),
            "source_pdf_sha256": m.get("source_pdf_sha256"),
            "notes": f"Norme relue champ par champ depuis le brouillon {review.draft.name}.",
            "extends": extends,
            "refers_to": [r for n in extends for r in review.references if r["norm"] == n],
            "applies": "always", "validated_by": None, "validated_at": None}
    return {"meta": meta, **data, "sources": dict(sorted(sources.items()))}


def _completed_norm(review: Review) -> dict[str, Any]:
    data = read_yaml(review.norm_base)
    meta = dict(data.pop("meta"))
    sources: dict[str, str] = dict(data.pop("sources", None) or {})
    for d in review.decisions:
        if d.action in ("accept", "correct"):
            _set(data, d.path, d.value)
            sources[d.path] = d.source
        elif d.action == "empty":
            _delete(data, d.path)
            sources.pop(d.path, None)
    refs = {r["norm"]: r for r in meta.get("refers_to") or []}
    refs.update({r["norm"]: r for r in review.references})
    meta["extends"] = with_references(list(meta.get("extends") or []), review.references)
    meta["refers_to"] = [refs[n] for n in meta["extends"] if n in refs]
    meta["notes"] = f"{meta.get('notes') or ''} Complétée depuis le brouillon {review.draft.name}.".strip()
    return {"meta": meta, **data, "sources": dict(sorted(sources.items()))}


def write_norm(review: Review, out: Path, data: dict[str, Any]) -> Path:
    """Check the norm (schema, a source for every value, the norms it extends, no cycle), written in a
    folder of its own next to ``out``; returns that file, to move in place with ``finish``."""
    tmp = out.parent / ".relecture" / out.name  # same file name: meta.name must match it
    tmp.parent.mkdir(parents=True, exist_ok=True)
    d = data["meta"]["document"]
    header = [f"Norme {data['meta']['name']} relue avec pad-guard review-profile depuis {review.draft.name}.",
              f"Document : {d['title']} ({d['version']}), {data['meta']['source_pdf']} "
              f"(SHA-256 {data['meta']['source_pdf_sha256']}).",
              "Chaque valeur cite sa page dans « sources » ; aucune valeur des normes étendues n'est recopiée."]
    tmp.write_text(dump(data, None, header), encoding="utf-8", newline="\n")
    try:
        norm = load_norm(tmp)
        _norm_chain(norm.meta.extends, out.parent, f"normes/{norm.name}.yaml", [norm.name], {}, [], tmp)
    except ProfileError as exc:
        tmp.unlink(missing_ok=True)
        raise ReviewError("norme invalide, rien n'a été écrit :\n  - " + "\n  - ".join(exc.messages)) from None
    return tmp


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
