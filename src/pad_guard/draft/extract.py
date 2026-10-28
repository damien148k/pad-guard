"""Ask the local model for profile values, page batch by page batch, then check and merge (SPEC §13).

Every finding is checked deterministically (:mod:`pad_guard.draft.verify`): only a value whose
quote is in the page it names, and whose number is in that quote, is kept. Two checked values
that differ for one field are both kept and the field is a CONFLIT, for a human to settle.
Nothing is ever chosen silently.

A checked value out of the plausible range of the glossary, or cited with a unit the field does
not accept, is kept but INVRAISEMBLABLE. A reference to a norm without its value (« conforme à
la R128 ») gives no value: the field is RENVOI_NORME and the norm is proposed in ``meta.extends``.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from pad_guard.draft import examples as examples_mod
from pad_guard.draft import verify, vocabulary
from pad_guard.draft.glossary import Glossary, implausible
from pad_guard.draft.pdf import Document, render
from pad_guard.draft.schema import MAX_FINDINGS, FieldSpec, catalogue, check_value, response_schema
from pad_guard.llm import LLMClient, LLMError, LLMRequest
from pad_guard.llm.client import request_fingerprint as fingerprint

PROMPT_VERSION = "draft_profile_v2"
PROMPT_FILE = Path(__file__).resolve().parents[1] / "llm" / "prompts" / f"{PROMPT_VERSION}.md"
PAGES_PER_BATCH = 2
MAX_IMAGES_PER_BATCH = 2
MAX_QUOTE_CHARS = 300  # a quote is a sentence or a table row, not a paragraph

# Context size of a run (num_ctx), from an upper estimate of the largest request. Measured on qwen3-vl
# (Arte V2-01-03, France TV 2023): 0.20 to 0.29 token per character, about 1300 tokens per rendered page,
# largest request 9195 tokens, longest answer 7960 tokens (Arte p. 87-88, 116 proposals).
TOKENS_PER_CHAR = 0.33
TOKENS_PER_IMAGE = 2000
ANSWER_TOKENS = 10240
CONTEXT_STEP = 1024

# Status of one finding, then of one field.
OK = "A_VERIFIER"  # quote found in its page, number in the quote: still to be reviewed by a human
INVALID = "CITATION_INVALIDE"
UNVERIFIABLE = "CITATION_NON_VERIFIABLE"  # the page has no text layer
BAD_VALUE = "VALEUR_INVALIDE"  # not of the field's type
IMPLAUSIBLE = "INVRAISEMBLABLE"  # citation checked, value out of range or unit not accepted: kept, shown in red
NORM_REF = "RENVOI_NORME"  # the document refers to a norm without writing the value: no value
CONFLICT = "CONFLIT"

CLIENT_VALUE, REFERS_TO_NORM, NOT_FOUND = "client_value", "client_refers_to_norm", "not_found"

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
    source_type: str = CLIENT_VALUE
    norm: str | None = None  # RENVOI_NORME: glossary key of the norm, or its name as written if unknown


@dataclass
class Context:
    """What the prompt is given besides the pages: glossary and examples of other broadcasters."""

    glossary: Glossary | None = None
    examples: dict[str, list[examples_mod.Example]] = field(default_factory=dict)


@dataclass
class FieldResult:
    path: str
    description: str
    status: str
    value: Any = None  # the checked value; None unless status is A_VERIFIER or INVRAISEMBLABLE
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
    num_ctx: int | None = None  # context size of the run, in tokens
    capped_pages: list[int] = field(default_factory=list)  # pages alone still at MAX_FINDINGS

    def cited_norms(self) -> dict[str, Finding]:
        """Norms the document refers to (glossary key or name as written), with their first citation."""
        out: dict[str, Finding] = {}
        for r in self.fields:
            for f in r.findings:
                if f.status == NORM_REF and f.norm and f.norm not in out:
                    out[f.norm] = f
        return dict(sorted(out.items(), key=lambda kv: (kv[1].page, kv[0])))


def system_prompt() -> str:
    return PROMPT_FILE.read_text(encoding="utf-8")


def field_list(fields: list[FieldSpec]) -> str:
    """Fields shown to the model; internal PAD Guard parameters are left out (still in the schema)."""
    return "\n".join(f"- {f.path} ({f.type_text}) : {f.description}" for f in fields
                     if f.path not in vocabulary.INTERNAL)


def batches(doc: Document, size: int = PAGES_PER_BATCH) -> list[list[int]]:
    numbers = [p.number for p in doc.pages]
    return [numbers[i: i + size] for i in range(0, len(numbers), size)]


def batch_fields(doc: Document, pages: list[int], context: Context) -> list[str]:
    """Fields whose glossary terms appear in the pages: their glossary and examples are shown."""
    if context.glossary is None:
        return []
    text = "\n".join(doc.page(n).full_text for n in pages)
    return [p for p in context.glossary.fields_in(text) if p not in vocabulary.INTERNAL]


def build_prompt(doc: Document, pages: list[int], fields: list[FieldSpec], context: Context | None = None) -> str:
    context = context or Context()
    text = "\n\n".join(f"=== Page {n} ===\n{doc.page(n).full_text or '(page sans texte : voir l’image)'}"
                       for n in pages)
    extra = ""
    hits = batch_fields(doc, pages, context)
    if hits:
        extra += ("Glossaire des champs dont un terme figure dans ces pages (termes, unités, contextes) :\n"
                  f"{context.glossary.prompt_block(hits)}\n\n")
        shown = examples_mod.prompt_block(context.examples, hits)
        if shown:
            extra += ("Exemples tirés de profils validés d'autres diffuseurs (ne reprends jamais leurs valeurs) :\n"
                      f"{shown}\n\n")
    return (f"Champs du profil (chemin, type, description) :\n{field_list(fields)}\n\n{extra}"
            f"Pages {pages[0]} à {pages[-1]} du document « {doc.path.name} » :\n\n{text}\n\n"
            "Extrais les valeurs de ces pages selon les règles.")


def _page_and_quote(doc: Document, f: Finding, pages: list[int]):
    """(page, table row or None) when the quote is found in its page, else None with f.status set."""
    page = doc.page(f.page) if isinstance(f.page, int) else None
    if page is None or f.page not in pages:
        f.status, f.reason = INVALID, f"page {f.page} absente du lot de pages {pages[0]}-{pages[-1]}"
        return None
    if not page.has_text:
        f.status, f.reason = UNVERIFIABLE, "page sans couche texte : citation non vérifiable"
        return None
    if f.field in vocabulary.INTERNAL:
        f.status, f.reason = INVALID, "paramètre interne à PAD Guard : il ne vient pas du document"
        return None
    if len(verify.normalise(f.quote)) > MAX_QUOTE_CHARS:
        f.status, f.reason = INVALID, f"citation trop longue (plus de {MAX_QUOTE_CHARS} caractères)"
        return None
    if verify.quote_in(f.quote, page.full_text):
        return page, (verify.table_row(f.quote, page.tables) if page.tables else None)
    in_table = verify.table_row(f.quote, page.tables)
    if in_table is None:
        elsewhere = [p.number for p in doc.pages if p.number != f.page and verify.quote_in(f.quote, p.full_text)]
        f.status = INVALID
        f.reason = "citation introuvable dans la page" + (f" (trouvée p. {elsewhere[0]})" if elsewhere else "")
        return None
    return page, in_table


def _missing_words(f: Finding, glossary: Glossary | None) -> str | None:
    words = vocabulary.missing_words(f.field, f.quote)
    if words and glossary is not None and glossary.has_term(f.field, f.quote):
        return None  # a term of the reviewed glossary names the field
    return words


def _check_reference(doc: Document, f: Finding, pages: list[int], glossary: Glossary | None) -> Finding:
    """client_refers_to_norm: the quote is in its page, speaks of the field and names a norm. Never a value."""
    if f.value is not None:
        f.reason = "valeur proposée ignorée : le document renvoie à une norme sans écrire la valeur"
    f.value = None
    if _page_and_quote(doc, f, pages) is None:
        return f
    words = _missing_words(f, glossary)
    if words:
        f.status, f.reason, f.norm = INVALID, f"citation sans rapport avec le champ (mots attendus : {words})", None
        return f
    keys = glossary.norms_in(f.quote) if glossary else []
    if keys:
        f.norm = keys[0]
    elif f.norm and any(c.isdigit() for c in f.norm) and verify.quote_in(f.norm, f.quote):
        # A norm unknown to the glossary, named as in the document: a reference always has a number
        # (« Tech. 3264 », « ST 2084 »); « Latin » or « TC IN » are not norms.
        f.norm = " ".join(f.norm.split())
    else:
        f.status, f.reason, f.norm = INVALID, "la citation ne nomme aucune norme", None
        return f
    f.status = NORM_REF
    return f


def check(doc: Document, raw: dict, specs: dict[str, FieldSpec], batch: int, pages: list[int],
          glossary: Glossary | None = None) -> Finding:
    f = Finding(field=str(raw.get("field")), value=raw.get("value"), page=raw.get("page") or 0,
                quote=str(raw.get("quote") or ""), unit=raw.get("unit"), status=OK, batch=batch,
                source_type=raw.get("source_type") or CLIENT_VALUE, norm=raw.get("norm"))
    spec = specs.get(f.field)
    if spec is None:
        f.status, f.reason = BAD_VALUE, "champ inconnu du profil"
        return f
    if f.source_type == REFERS_TO_NORM:
        return _check_reference(doc, f, pages, glossary)
    value, why = check_value(spec, f.value)
    if why:
        f.status, f.reason = BAD_VALUE, why
        return f
    value, note = _without_note_marks(f.field, value)
    found = _page_and_quote(doc, f, pages)
    if found is None:
        return f
    page, in_table = found
    columns: set[str] = set()
    if in_table is not None and ".loudness." in f.field and (".long." in f.field or ".short." in f.field):
        columns = verify.table_column_kinds(value, *in_table)
        wanted = "long" if ".long." in f.field else "short"
        if columns and wanted not in columns:
            f.status = INVALID
            f.reason = f"dans le tableau, la valeur est dans la colonne des programmes {'longs' if 'long' in columns else 'courts'}"
            return f
    words = _missing_words(f, glossary)
    if words:
        f.status, f.reason = INVALID, f"citation sans rapport avec le champ (mots attendus : {words})"
        return f
    why = vocabulary.evidence(f.field, json.dumps(value), f.quote)
    if why is None and f.field in vocabulary.LITERAL_TEXT and isinstance(value, str):
        if " ".join(vocabulary.plain(value).split()) not in " ".join(vocabulary.plain(f.quote).split()):
            why = f"la citation ne contient pas le texte « {value} »"
    if why:
        f.status, f.reason = INVALID, why
        return f
    numeric = _number(value) or (isinstance(value, list) and bool(value) and all(_number(v) for v in value))
    # The column of the table says which programmes a value is for; the page text read in order does not.
    why = (verify.value_in_quote(value, f.quote, vocabulary.unit_of(f.field) if numeric else None)
           or (None if columns else verify.loudness_context(f.field, f.quote, page.full_text)))
    if why:
        f.status, f.reason = INVALID, why
        return f
    f.value = value
    f.reason = note
    why = implausible(glossary, f.field, value, f.unit) if glossary is not None else None
    if why:
        f.status, f.reason = IMPLAUSIBLE, why
    return f


_NOTE_MARKS = re.compile(r"\s*[*†‡¹²³]+$")


def _without_note_marks(path: str, value: Any) -> tuple[Any, str]:
    """Footnote marks copied from a table cell (« 1.33* ») removed from the image formats; the
    quote keeps them, the reason says it."""
    if path != "format.letterbox.formats" or not isinstance(value, list):
        return value, ""
    cleaned = [{**v, "aspect": _NOTE_MARKS.sub("", v["aspect"])} if isinstance(v.get("aspect"), str) else v
               for v in value]
    changed = [v["aspect"] for v in value if isinstance(v.get("aspect"), str) and _NOTE_MARKS.search(v["aspect"])]
    return cleaned, (f"renvoi de note retiré de aspect : {', '.join(changed)}" if changed else "")


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def canonical(value: Any) -> str:
    """Comparison key of a value: a list of plain values is a set (["50/1", "25/1"] = ["25/1", "50/1"])."""
    if isinstance(value, list) and all(not isinstance(v, (dict, list)) for v in value):
        value = sorted(set(map(json.dumps, value)))
    return json.dumps(value, sort_keys=True)


def flag_shared_quotes(findings: list[Finding]) -> None:
    """One quote and one number given for two different fields: which field is meant is ambiguous.

    Only numbers: one sentence may well say « BT.709 » for the three colour fields, or forbid
    two things at once."""
    groups: dict[tuple[str, str], list[Finding]] = {}
    for f in findings:
        if f.status == OK and _number(f.value):
            groups.setdefault((verify.normalise(f.quote), canonical(f.value)), []).append(f)
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
        values, keys = [], set()
        for f in found:  # checked citations, plausible or not: an implausible value still conflicts
            if f.status in (OK, IMPLAUSIBLE) and canonical(f.value) not in keys:
                keys.add(canonical(f.value))
                values.append(f.value)
        if any(f.status == CONFLICT for f in found) or len(values) > 1:
            status, value = CONFLICT, None  # two values, or a value whose field is ambiguous
        elif values:
            plausible = any(f.status == OK for f in found)
            status, value = (OK if plausible else IMPLAUSIBLE), values[0]
        elif any(f.status == NORM_REF for f in found):
            status, value = NORM_REF, None
        else:
            statuses = {f.status for f in found}
            status, value = next(s for s in (UNVERIFIABLE, INVALID, BAD_VALUE) if s in statuses), None
        results.append(FieldResult(spec.path, spec.description, status, value, found))
    unknown = sorted({f.field for f in findings} - {s.path for s in fields})
    for name in unknown:
        results.append(FieldResult(name, "", BAD_VALUE, None, by_field[name]))
    return results, missing


def extract(doc: Document, client: LLMClient, progress: Progress | None = None,
            pages_per_batch: int = PAGES_PER_BATCH, timeout: float = 600.0,
            context: Context | None = None, system: str | None = None) -> Extraction:
    """``system``: the system prompt, by default the versioned file of PROMPT_VERSION (a test bench
    passes a frozen copy)."""
    context = context or Context()
    fields = catalogue()
    specs = {f.path: f for f in fields}
    schema = response_schema(fields)
    system = system if system is not None else system_prompt()
    system_sha = hashlib.sha256(system.encode("utf-8")).hexdigest()
    glossary_sha = context.glossary.sha256 if context.glossary is not None else None
    plan = batches(doc, pages_per_batch)
    prompts = [build_prompt(doc, pages, fields, context) for pages in plan]
    fit_context(client, doc, plan, prompts, system)
    if progress:
        progress(0, len(plan))  # context fixed, first request next
    findings: list[Finding] = []
    log: list[dict] = []
    capped: list[int] = []

    def ask(batch: int, pages: list[int], prompt: str, retry: bool) -> list[dict]:
        images = tuple(render(doc.path, n) for n in pages if doc.page(n).needs_image)[:MAX_IMAGES_PER_BATCH]
        request = LLMRequest(prompt=prompt, schema=schema, system=system, images=images, timeout=timeout)
        where = f"page {pages[0]}" if len(pages) == 1 else f"pages {pages[0]}-{pages[-1]}"
        try:
            raw = client.generate(request)
        except LLMError as exc:
            raise DraftError(f"{where} : {exc}") from None
        usage = client.usage()
        log.append({"batch": batch, "pages": pages, "retry_page_by_page": retry, "model": client.model,
                    "prompt_version": PROMPT_VERSION, "options": client.settings(), "max_findings": MAX_FINDINGS,
                    "system_sha256": system_sha, "glossary_sha256": glossary_sha,
                    "prompt_sha256": fingerprint(system, prompt, images, schema), "images": len(images),
                    "num_ctx": client.num_ctx, "prompt_tokens": usage.prompt_tokens if usage else None,
                    "output_tokens": usage.output_tokens if usage else None, "response": raw})
        try:
            items = json.loads(raw)["findings"]
            if not isinstance(items, list) or not all(isinstance(x, dict) for x in items):
                raise TypeError("findings n'est pas une liste d'objets")
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise DraftError(f"{where} : réponse du modèle mal formée ({exc.__class__.__name__}: {exc}). "
                             "Aucun brouillon n'a été écrit.") from None
        return items

    for i, (pages, prompt) in enumerate(zip(plan, prompts), start=1):
        answers = [(pages, ask(i, pages, prompt, retry=False))]
        if len(answers[0][1]) >= MAX_FINDINGS:
            if len(pages) > 1:  # the limit may have cut proposals: each page asked alone
                answers = [([n], ask(i, [n], build_prompt(doc, [n], fields, context), retry=True)) for n in pages]
            capped += [n[0] for n, items in answers if len(n) == 1 and len(items) >= MAX_FINDINGS]
        for asked, items in answers:
            # not_found answers say nothing: they stay in the log only.
            findings += [check(doc, x, specs, i, asked, context.glossary) for x in items
                         if x.get("source_type") != NOT_FOUND]
        if progress:
            progress(i, len(plan))
    results, missing = merge(findings, fields)
    return Extraction(model=client.model, prompt_version=PROMPT_VERSION, pdf_sha256=doc.sha256,
                      pages=len(doc.pages), batches=len(plan), fields=results, not_found=missing, log=log,
                      num_ctx=client.num_ctx, capped_pages=capped)


def estimate_tokens(system: str, prompt: str, images: int) -> int:
    """Upper estimate of the prompt tokens of one request (measured on qwen3-vl, 52 requests of the
    Arte and France TV documents: at most 97 % of this estimate)."""
    return math.ceil(TOKENS_PER_CHAR * (len(system) + len(prompt)) + TOKENS_PER_IMAGE * images)


def needed_context(doc: Document, plan: list[list[int]], prompts: list[str], system: str) -> tuple[int, int, list[int]]:
    """(context size for the whole run, estimate of the largest request, its pages)."""
    sizes = [(estimate_tokens(system, prompt, min(sum(doc.page(n).needs_image for n in pages), MAX_IMAGES_PER_BATCH)),
              pages) for pages, prompt in zip(plan, prompts)]
    biggest, pages = max(sizes, key=lambda s: s[0]) if sizes else (0, [])
    return -(-(biggest + ANSWER_TOKENS) // CONTEXT_STEP) * CONTEXT_STEP, biggest, pages


def fit_context(client: LLMClient, doc: Document, plan: list[list[int]], prompts: list[str], system: str) -> None:
    """Set the context of the run when the caller did not, or refuse before the first request when
    the context it set is too small: never a request cut by the engine, never an answer cut short."""
    needed, biggest, pages = needed_context(doc, plan, prompts, system)
    if client.num_ctx is None:
        client.num_ctx = needed
    elif client.num_ctx < needed:
        raise DraftError(f"contexte de {client.num_ctx} jetons trop petit : la plus grosse demande (pages {pages[0]}-"
                         f"{pages[-1]}) est estimée à {biggest} jetons, plus {ANSWER_TOKENS} réservés à la réponse. "
                         f"Relancer avec --num-ctx {needed}, ou sans --num-ctx (calcul automatique). "
                         "Aucun brouillon n'a été écrit.")
