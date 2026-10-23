"""Ask the local model for profile values, page batch by page batch, then check and merge (SPEC §13).

Every finding is checked deterministically (:mod:`pad_checker.draft.verify`): only a value whose
quote is in the page it names, and whose number is in that quote, is kept. Two checked values
that differ for one field are both kept and the field is a CONFLIT, for a human to settle.
Nothing is ever chosen silently.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pad_checker.draft import verify, vocabulary
from pad_checker.draft.pdf import Document, render
from pad_checker.draft.schema import FieldSpec, catalogue, check_value, response_schema
from pad_checker.llm import LLMClient, LLMError, LLMRequest

PROMPT_VERSION = "draft_profile_v1"
PROMPT_FILE = Path(__file__).resolve().parents[1] / "llm" / "prompts" / f"{PROMPT_VERSION}.md"
PAGES_PER_BATCH = 2
MAX_IMAGES_PER_BATCH = 2
MAX_QUOTE_CHARS = 300  # a quote is a sentence or a table row, not a paragraph

# Status of one finding, then of one field.
OK = "A_VERIFIER"  # quote found in its page, number in the quote: still to be reviewed by a human
INVALID = "CITATION_INVALIDE"
UNVERIFIABLE = "CITATION_NON_VERIFIABLE"  # the page has no text layer
BAD_VALUE = "VALEUR_INVALIDE"  # not of the field's type
CONFLICT = "CONFLIT"

Progress = Callable[[int, int], None]  # (batches done, batches)


class DraftError(Exception):
    """The draft cannot be made. The message is user-facing (French)."""


@dataclass
class Finding:
    field: str
    value: Any  # as proposed by the model (or converted to the field type when valid)
    page: int
    quote: str
    unit: str | None
    status: str
    reason: str = ""
    batch: int = 0


@dataclass
class FieldResult:
    path: str
    description: str
    status: str
    value: Any = None  # the checked value; None unless status is A_VERIFIER
    findings: list[Finding] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"path": self.path, "description": self.description, "status": self.status, "value": self.value,
                "findings": [asdict(f) for f in self.findings]}


@dataclass
class Extraction:
    model: str
    prompt_version: str
    pdf_sha256: str
    pages: int
    batches: int
    fields: list[FieldResult]  # fields with at least one finding, catalogue order
    not_found: list[str]  # catalogue paths with no finding at all
    log: list[dict]  # raw model answers, one per batch


def system_prompt() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8")


def field_list(fields: list[FieldSpec]) -> str:
    """Fields shown to the model; internal pad-checker parameters are left out (still in the schema)."""
    return "\n".join(f"- {f.path} ({f.type_text}) : {f.description}" for f in fields
                     if f.path not in vocabulary.INTERNAL)


def batches(doc: Document, size: int = PAGES_PER_BATCH) -> list[list[int]]:
    numbers = [p.number for p in doc.pages]
    return [numbers[i: i + size] for i in range(0, len(numbers), size)]


def build_prompt(doc: Document, pages: list[int], fields: list[FieldSpec]) -> str:
    text = "\n\n".join(f"=== Page {n} ===\n{doc.page(n).full_text or '(page sans texte : voir l’image)'}"
                       for n in pages)
    return (f"Champs du profil (chemin, type, description) :\n{field_list(fields)}\n\n"
            f"Pages {pages[0]} à {pages[-1]} du document « {doc.path.name} » :\n\n{text}\n\n"
            "Extrais les valeurs de ces pages selon les règles.")


def check(doc: Document, raw: dict, specs: dict[str, FieldSpec], batch: int, pages: list[int]) -> Finding:
    f = Finding(field=str(raw.get("field")), value=raw.get("value"), page=raw.get("page") or 0,
                quote=str(raw.get("quote") or ""), unit=raw.get("unit"), status=OK, batch=batch)
    spec = specs.get(f.field)
    if spec is None:
        f.status, f.reason = BAD_VALUE, "champ inconnu du profil"
        return f
    value, why = check_value(spec, f.value)
    if why:
        f.status, f.reason = BAD_VALUE, why
        return f
    page = doc.page(f.page) if isinstance(f.page, int) else None
    if page is None or f.page not in pages:
        f.status, f.reason = INVALID, f"page {f.page} absente du lot de pages {pages[0]}-{pages[-1]}"
        return f
    if not page.has_text:
        f.status, f.reason = UNVERIFIABLE, "page sans couche texte : citation non vérifiable"
        return f
    if f.field in vocabulary.INTERNAL:
        f.status, f.reason = INVALID, "paramètre interne à pad-checker : il ne vient pas du document"
        return f
    if len(verify.normalise(f.quote)) > MAX_QUOTE_CHARS:
        f.status, f.reason = INVALID, f"citation trop longue (plus de {MAX_QUOTE_CHARS} caractères)"
        return f
    if not verify.quote_in(f.quote, page.full_text):
        elsewhere = [p.number for p in doc.pages if p.number != f.page and verify.quote_in(f.quote, p.full_text)]
        f.status = INVALID
        f.reason = "citation introuvable dans la page" + (f" (trouvée p. {elsewhere[0]})" if elsewhere else "")
        return f
    words = vocabulary.missing_words(f.field, f.quote)
    if words:
        f.status, f.reason = INVALID, f"citation sans rapport avec le champ (mots attendus : {words})"
        return f
    scalar = isinstance(value, (int, float)) and not isinstance(value, bool)
    why = (verify.value_in_quote(value, f.quote, vocabulary.unit_of(f.field) if scalar else None)
           or verify.loudness_context(f.field, f.quote, page.full_text))
    if why:
        f.status, f.reason = INVALID, why
        return f
    f.value = value
    return f


def flag_shared_quotes(findings: list[Finding]) -> None:
    """One quote and one value given for two different fields: which field is meant is ambiguous."""
    groups: dict[tuple[str, str], list[Finding]] = {}
    for f in findings:
        if f.status == OK:
            groups.setdefault((verify.normalise(f.quote), json.dumps(f.value, sort_keys=True)), []).append(f)
    for same in groups.values():
        fields = sorted({f.field for f in same})
        if len(fields) > 1:
            for f in same:
                f.status = CONFLICT
                f.reason = "même citation et même valeur que " + ", ".join(x for x in fields if x != f.field)


def merge(findings: list[Finding], fields: list[FieldSpec]) -> tuple[list[FieldResult], list[str]]:
    flag_shared_quotes(findings)
    by_field: dict[str, list[Finding]] = {}
    for f in findings:
        by_field.setdefault(f.field, []).append(f)
    results, missing = [], []
    for spec in fields:
        found = by_field.get(spec.path)
        if not found:
            missing.append(spec.path)
            continue
        values = []
        for f in found:
            if f.status == OK and f.value not in values:
                values.append(f.value)
        if any(f.status == CONFLICT for f in found) or len(values) > 1:
            status, value = CONFLICT, None  # two values, or a value whose field is ambiguous
        elif values:
            status, value = OK, values[0]
        else:
            statuses = {f.status for f in found}
            status, value = next(s for s in (UNVERIFIABLE, INVALID, BAD_VALUE) if s in statuses), None
        results.append(FieldResult(spec.path, spec.description, status, value, found))
    unknown = sorted({f.field for f in findings} - {s.path for s in fields})
    for name in unknown:
        results.append(FieldResult(name, "", BAD_VALUE, None, by_field[name]))
    return results, missing


def extract(doc: Document, client: LLMClient, progress: Progress | None = None,
            pages_per_batch: int = PAGES_PER_BATCH, timeout: float = 600.0) -> Extraction:
    fields = catalogue()
    specs = {f.path: f for f in fields}
    schema = response_schema(fields)
    system = system_prompt()
    plan = batches(doc, pages_per_batch)
    findings: list[Finding] = []
    log: list[dict] = []
    for i, pages in enumerate(plan, start=1):
        images = tuple(render(doc.path, n) for n in pages if doc.page(n).needs_image)[:MAX_IMAGES_PER_BATCH]
        request = LLMRequest(prompt=build_prompt(doc, pages, fields), schema=schema, system=system,
                             images=images, timeout=timeout)
        where = f"pages {pages[0]}-{pages[-1]}"
        try:
            raw = client.generate(request)
        except LLMError as exc:
            raise DraftError(f"{where} : {exc}") from None
        log.append({"batch": i, "pages": pages, "model": client.model, "prompt_version": PROMPT_VERSION,
                    "images": len(images), "response": raw})
        try:
            data = json.loads(raw)
            items = data["findings"]
            if not isinstance(items, list) or not all(isinstance(x, dict) for x in items):
                raise TypeError("findings n'est pas une liste d'objets")
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise DraftError(f"{where} : réponse du modèle mal formée ({exc.__class__.__name__}: {exc}). "
                             "Aucun brouillon n'a été écrit.") from None
        findings += [check(doc, x, specs, i, pages) for x in items]
        if progress:
            progress(i, len(plan))
    results, missing = merge(findings, fields)
    return Extraction(model=client.model, prompt_version=PROMPT_VERSION, pdf_sha256=doc.sha256,
                      pages=len(doc.pages), batches=len(plan), fields=results, not_found=missing, log=log)
