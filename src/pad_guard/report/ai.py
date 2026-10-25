"""Section 3 « Synthèse » and the « Qualif. suggérée » column, written by the local model (SPEC §8.1).

The model never touches the verdict, the score, the severities, the events or the measurements: it
is given them (never the frame-by-frame measurements) and writes text. Everything it writes is
checked here, deterministically: every number, timecode, anomaly number and event type must be in
the data it was given, and the verdict it writes must be the one of verdict.json. A synthesis that
fails a check is replaced by the template synthesis, with a warning in the report; a qualification
that fails is left empty for its rows only.

Requests (a bounded context per request, SPEC §8.1): one per picture event with a thumbnail (the
thumbnail is sent: vision), one per family of other events (same type, group and severity, e.g. the
silences of one group), then one for the synthesis, which is given the qualifications kept.

Everything sent and received is recorded in llm_synthese.json, with the fingerprint of the prompt,
the inputs and the model. A later report with the same fingerprint replays the recorded answers
through the same checks without calling the model: same inputs, same report.
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import math
import re
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from pad_guard import workdir as wd
from pad_guard.llm import DEFAULT_MODEL, LLMClient, LLMError, LLMRequest, OllamaClient, pick_model
from pad_guard.llm import request_fingerprint

PROMPT_VERSION = "synthese_v1"
PROMPT_FILE = Path(__file__).resolve().parents[1] / "llm" / "prompts" / f"{PROMPT_VERSION}.md"
FILE_VERSION = 1

QUALIFICATIONS = ("défaut à corriger", "choix artistique probable", "faux positif probable",
                  "à vérifier à l'image", "à vérifier à l'écoute")
QUALIFIED_SEVERITIES = ("bloquant", "majeur", "mineur")  # French labels, as the model sees them
MIN_PARAGRAPHS, MAX_PARAGRAPHS = 2, 4
MAX_JUSTIFICATION_CHARS = 400
TIMEOUT = 300.0  # seconds per request

# Context of a run (num_ctx), from an upper estimate of the largest request (the draft-profile
# measures: at most 0.29 token per character of French text and JSON). Image tokens: one per
# 28 x 28 pixels, a bound for Qwen-VL (32 x 32 per token for Qwen3-VL).
TOKENS_PER_CHAR = 0.33
IMAGE_PIXELS_PER_TOKEN = 28
ANSWER_TOKENS = 3072
CONTEXT_STEP = 1024
MAX_CONTEXT = 32768

RETRY_HINT = ("\n\nTa réponse précédente ne respectait pas le schéma JSON imposé. Réponds uniquement par un objet "
              "JSON conforme au schéma.")

QUALIFICATION_SCHEMA = {
    "type": "object",
    "properties": {"qualifications": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "anomalies": {"type": "array", "items": {"type": "integer"}, "minItems": 1},
            "qualification": {"type": "string", "enum": list(QUALIFICATIONS)},
            "justification": {"type": "string"},
        },
        "required": ["anomalies", "qualification", "justification"],
    }}},
    "required": ["qualifications"],
}
SYNTHESIS_SCHEMA = {
    "type": "object",
    "properties": {"synthese": {"type": "array", "items": {"type": "string"},
                                "minItems": MIN_PARAGRAPHS, "maxItems": MAX_PARAGRAPHS}},
    "required": ["synthese"],
}

Progress = Callable[[str], None]


@dataclass(frozen=True)
class Qualification:
    value: str  # one of QUALIFICATIONS
    justification: str


@dataclass
class Outcome:
    """What the report shows. ``paragraphs`` None: the template synthesis, for ``fallback``."""

    model: str | None
    paragraphs: list[str] | None
    fallback: str | None  # French, why the synthesis of the model was not kept
    qualifications: dict[int, Qualification] = field(default_factory=dict)
    rejected: dict[int, str] = field(default_factory=dict)  # event id -> why its qualification is empty
    requested: int = 0  # events to qualify (blocking, major, minor)
    reused: bool = False  # answers replayed from llm_synthese.json
    calls: int = 0  # requests sent to the model by this run
    elapsed: float | None = None  # seconds spent in the model by this run
    num_ctx: int | None = None


@dataclass
class Options:
    model: str | None = None  # None: DEFAULT_MODEL
    refresh: bool = False  # call the model even when llm_synthese.json matches the inputs
    client: LLMClient | None = None  # tests: a fake client; None: OllamaClient
    timeout: float = TIMEOUT
    outcome: Outcome | None = None  # set by run(), for the command line


def failed(reason: str, requested: int = 0) -> Outcome:
    return Outcome(model=None, paragraphs=None, fallback=reason, requested=requested)


# --- checks -------------------------------------------------------------------------------------

_TC = re.compile(r"(?<![\d:])\d{2}:\d{2}:\d{2}[:;]\d{2}(?![\d:])")
_COLON_NUMBER = re.compile(r"\d+(?::\d+)+")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_THOUSANDS = re.compile(r"(?<![\d.,])\d{1,3}(?:[   ]\d{3})+(?![\d])")
_IDS = re.compile(r"(?i)(?:\banomalies?|\bn°|\bnuméros?|\bévénements?|#)\s*(\d+(?:\s*(?:,|et|à|-|ou)\s*\d+)*)")
_SNAKE = re.compile(r"\b[a-z0-9]+(?:_[a-z0-9]+)+\b")
# An event exists because its rule's threshold was crossed: a text saying otherwise contradicts the rules.
_WITHIN_THRESHOLD = re.compile(r"(?i)\brespect\w*\s+(?:(?:le|les|du|des|son|leur|leurs)\s+)?seuils?\b"
                               r"|\b(?:reste|restent|est|sont)\s+dans\s+(?:les\s+limites|la\s+tolérance)")
_CONFORME = re.compile(r"(?i)(?<!non-)(?<!non )\bconform(?:e|es|ité|ités)\b")
_HYPHENS = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-"})

_NUMBER_WORDS = {
    "zéro": 0, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5, "six": 6, "sept": 7, "huit": 8, "neuf": 9, "dix": 10,
    "onze": 11, "douze": 12, "treize": 13, "quatorze": 14, "quinze": 15, "seize": 16, "vingt": 20, "vingts": 20,
    "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60, "cent": 100, "cents": 100, "mille": 1000,
}
_WORDS = "|".join(sorted(_NUMBER_WORDS, key=len, reverse=True))
_NUMBER_WORD = re.compile(rf"(?i)\b(?:{_WORDS})(?:-(?:{_WORDS}|et|un|une))*\b")


def _word_value(words: str) -> int:
    """French number in words (« vingt-trois », « quatre-vingt-dix »); « un » alone is an article."""
    total = current = 0
    for part in words.lower().split("-"):
        if part == "et":
            continue
        v = 1 if part in ("un", "une") else _NUMBER_WORDS[part]
        if v == 100:
            current = max(current, 1) * 100
        elif v == 1000:
            total += max(current, 1) * 1000
            current = 0
        elif v == 20 and current == 4:
            current = 80
        else:
            current += v
    return total + current


def _clean(text: str) -> str:
    return unicodedata.normalize("NFC", text).translate(_HYPHENS)


class Allowed:
    """Numbers, timecodes, anomaly numbers and identifiers of the data given to the model."""

    def __init__(self, data_text: str, ids: set[int]):
        text = _clean(data_text)
        self.tcs = set(_TC.findall(text))
        rest = _TC.sub(" ", text)
        self.strings: set[str] = set()
        self.values: set[Decimal] = set()
        for token in _NUMBER.findall(rest):
            s = token.replace(",", ".")
            self.strings.add(s)
            if s.count(".") <= 1:
                self.values.add(Decimal(s))
        self.ids = ids
        self.identifiers = set(_SNAKE.findall(text))

    def number(self, token: str) -> bool:
        """Written as in the data, or the same value rounded for display (signs are words: ignored)."""
        s = token.replace(",", ".")
        if s in self.strings:
            return True
        if s.count(".") > 1:
            return False
        written = Decimal(s)
        decimals = len(s.split(".")[1]) if "." in s else 0
        half = Decimal(5).scaleb(-decimals - 1)
        return any(abs(v - written) <= half for v in self.values)


def text_problems(text: str, allowed: Allowed) -> list[str]:
    """What, in a text written by the model, is not in the data it was given (French)."""
    out: list[str] = []
    text = _clean(text)
    for tc in _TC.findall(text):
        if tc not in allowed.tcs:
            out.append(f"timecode {tc} absent des données")
    rest = _TC.sub(" ", text)
    for m in _COLON_NUMBER.findall(rest):
        out.append(f"« {m} » n'est pas un timecode des données")
    rest = _COLON_NUMBER.sub(" ", rest)
    for m in _IDS.finditer(rest):
        for n in re.findall(r"\d+", m[1]):
            if int(n) not in allowed.ids:
                out.append(f"anomalie {n} inexistante")
    for name in _SNAKE.findall(text):
        if name not in allowed.identifiers:
            out.append(f"type d'événement « {name} » inexistant")
    # « 130 958 » is one number when the data have it, else its parts are checked.
    rest = _THOUSANDS.sub(lambda m: " " if allowed.number(re.sub(r"\D", "", m[0])) else m[0], rest)
    for token in _NUMBER.findall(rest):
        if not allowed.number(token):
            out.append(f"nombre {token} absent des données")
    for m in _NUMBER_WORD.finditer(rest):
        if not allowed.number(str(_word_value(m[0]))):
            out.append(f"nombre « {m[0]} » absent des données")
    for m in _WITHIN_THRESHOLD.finditer(text):
        out.append(f"« {m[0]} » : une anomalie a toujours dépassé le seuil de sa règle")
    return list(dict.fromkeys(out))


def opening(verdict: dict) -> str:
    """First sentence the synthesis is asked to start with."""
    if verdict.get("technique"):
        return "Rapport technique, sans verdict de conformité."
    if not verdict["indicatif"]:
        return f"Verdict : {verdict['statut']}."
    shown = "NON-CONFORME" if verdict["statut"] == "NON-CONFORME" else "sans anomalie bloquante"
    return f"Résultat indicatif, profil non validé : {shown}."


def verdict_problems(text: str, verdict: dict) -> list[str]:
    """The verdict written must be the one of verdict.json (CLAUDE.md principles 1 and 7)."""
    t = _clean(text)
    low = t.lower()
    status, indicative, label = verdict["statut"], verdict["indicatif"], verdict["affiche"]
    out = []
    if verdict.get("technique"):  # no broadcaster: neither CONFORME nor NON-CONFORME may be written
        if "rapport technique" not in low:
            out.append("la mention « Rapport technique » manque")
        if re.search(r"(?i)conform", t):
            out.append("« conforme » ou « non conforme » écrit dans un rapport technique (aucun verdict)")
        return out
    if status == "NON-CONFORME":
        if "NON-CONFORME" not in t:
            out.append("le verdict NON-CONFORME n'est pas écrit")
    elif indicative:
        if "sans anomalie bloquante" not in low:
            out.append(f"le verdict « {label} » n'est pas écrit")
        if re.search(r"(?i)non[- ]conform", t):
            out.append(f"« non conforme » écrit alors que le verdict est « {label} »")
    else:
        if not re.search(r"(?<!NON-)(?<!NON )\bCONFORME\b", t):
            out.append("le verdict CONFORME n'est pas écrit")
        if re.search(r"(?i)non[- ]conform", t):
            out.append("« non conforme » écrit alors que le verdict est CONFORME")
    if (status == "NON-CONFORME" or indicative) and _CONFORME.search(t):
        out.append(f"le mot « conforme » est employé alors que le verdict est « {label} »")
    if indicative and "résultat indicatif" not in low:
        out.append("profil non validé : la mention « résultat indicatif » manque")
    if not indicative and re.search(r"(?i)\bindicati(?:f|ve)\b", t):
        out.append("« indicatif » écrit alors que le profil est validé")
    return out


def _canonical(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    key = " ".join(unicodedata.normalize("NFC", value).replace("’", "'").lower().split()).rstrip(".")
    return {q: q for q in QUALIFICATIONS}.get(key)


def check_qualifications(items: list, ids: tuple[int, ...], allowed: Allowed
                         ) -> tuple[dict[int, Qualification], dict[int, str]]:
    """Qualifications of one answer for the events ``ids`` of its request: (kept, rejected with why).

    A number for an event that is not in the request is ignored; a value outside the list, a
    justification that is missing, too long or that fails :func:`text_problems`, or two different
    qualifications for one event leave that event empty, never the others.
    """
    decided: dict[int, Qualification | str] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("anomalies"), list):
            continue
        targets = [n for n in item["anomalies"] if isinstance(n, int) and not isinstance(n, bool) and n in ids]
        value = _canonical(item.get("qualification"))
        just = item.get("justification")
        just = " ".join(just.split()) if isinstance(just, str) else ""
        if value is None:
            verdict: Qualification | str = f"qualification hors liste (« {item.get('qualification')} »)"
        elif not just:
            verdict = "justification absente"
        elif len(just) > MAX_JUSTIFICATION_CHARS:
            verdict = f"justification de plus de {MAX_JUSTIFICATION_CHARS} caractères"
        else:
            problems = text_problems(just, allowed)
            verdict = f"justification écartée : {problems[0]}" if problems else Qualification(value, just)
        for n in dict.fromkeys(targets):
            before = decided.get(n)
            if before is None:
                decided[n] = verdict
            elif isinstance(before, Qualification) and isinstance(verdict, Qualification) and before.value == verdict.value:
                continue  # same qualification twice: the first justification is kept
            elif not isinstance(before, str) or not before.startswith("qualifications contradictoires"):
                decided[n] = "qualifications contradictoires pour cette anomalie"
    kept = {n: q for n, q in decided.items() if isinstance(q, Qualification)}
    rejected = {n: q for n, q in decided.items() if isinstance(q, str)}
    rejected.update({n: "non qualifiée par le modèle" for n in ids if n not in decided})
    return kept, rejected


# --- requests -----------------------------------------------------------------------------------


class _Malformed(Exception):
    pass


def _parse_qualifications(raw: str) -> list:
    data = json.loads(raw)
    items = data["qualifications"]
    if not isinstance(items, list):
        raise TypeError("« qualifications » n'est pas une liste")
    return items


def _parse_synthesis(raw: str) -> list[str]:
    data = json.loads(raw)
    paragraphs = data["synthese"]
    if not isinstance(paragraphs, list) or not all(isinstance(p, str) for p in paragraphs):
        raise TypeError("« synthese » n'est pas une liste de textes")
    paragraphs = [" ".join(p.split()) for p in paragraphs if p.strip()]
    if not MIN_PARAGRAPHS <= len(paragraphs) <= MAX_PARAGRAPHS:
        raise ValueError(f"{len(paragraphs)} paragraphe(s) au lieu de {MIN_PARAGRAPHS} à {MAX_PARAGRAPHS}")
    return paragraphs


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _lines(events: list[dict]) -> str:
    return "[\n" + ",\n".join(_dump(e) for e in events) + "\n]"


@dataclass(frozen=True)
class _Ask:
    ids: tuple[int, ...]
    request: LLMRequest


class Plan:
    """The requests of one synthesis, from the inputs alone (deterministic)."""

    def __init__(self, system: str, context: dict, events: list[dict], images: dict[int, bytes],
                 timeout: float = TIMEOUT):
        self.system = system
        self.context = context
        self.events = events
        self.images = images
        self.timeout = timeout
        self.qualify = [e for e in events if e["gravite"] in QUALIFIED_SEVERITIES]
        families: dict[tuple, list[dict]] = {}
        groups: list[list[dict]] = []
        for e in self.qualify:
            if e["n"] in images:
                groups.append([e])
            else:
                key = (e["type"], e.get("groupe"), e["gravite"])
                if key not in families:
                    families[key] = []
                    groups.append(families[key])
                families[key].append(e)
        self.asks = [self._qualification(g) for g in sorted(groups, key=lambda g: g[0]["n"])]
        self.data_text = _dump(context) + "\n" + _lines(events)
        self.allowed = Allowed(self.data_text, {e["n"] for e in events})
        h = hashlib.sha256()
        for part in (PROMPT_VERSION, system, _dump(QUALIFICATION_SCHEMA), _dump(SYNTHESIS_SCHEMA),
                     json.dumps({"context": context, "events": events}, ensure_ascii=False, sort_keys=True),
                     *(f"{n}:{hashlib.sha256(images[n]).hexdigest()}" for n in sorted(images))):
            h.update(part.encode("utf-8"))
            h.update(b"\0")
        self.inputs_sha256 = h.hexdigest()

    def fingerprint(self, model: str) -> str:
        return hashlib.sha256(f"{model}\0{self.inputs_sha256}".encode("utf-8")).hexdigest()

    def _header(self) -> dict:
        return {k: self.context[k] for k in ("fichier", "profil", "verdict", "probe")}

    def _qualification(self, group: list[dict]) -> _Ask:
        ids = tuple(e["n"] for e in group)
        image = self.images.get(ids[0]) if len(ids) == 1 else None
        listed = ", ".join(str(n) for n in ids)
        prompt = (
            "Demande : qualification d'anomalies.\n\n"
            f"Contexte du contrôle (JSON) :\n{_dump(self._header())}\n\n"
            f"Anomalies à qualifier (JSON) :\n{_lines(group)}\n\n"
            + (f"Vignette jointe : anomalie {ids[0]}.\n" if image else "")
            + f"Qualifie chacune de ces anomalies (numéros {listed}). Chaque élément de « qualifications » donne la "
            "liste des numéros concernés, une qualification de la liste et une justification d'une phrase."
        )
        return _Ask(ids, LLMRequest(prompt=prompt, schema=QUALIFICATION_SCHEMA, system=self.system,
                                    images=(image,) if image else (), timeout=self.timeout))

    def synthesis(self, kept: dict[int, Qualification]) -> LLMRequest:
        qualifs = [{"n": n, "qualification": kept[n].value} for n in sorted(kept)]
        prompt = (
            "Demande : synthèse du rapport.\n\n"
            f"Données du contrôle (JSON) :\n{_dump(self.context)}\n\n"
            f"Anomalies (JSON, ordre chronologique) :\n{_lines(self.events)}\n\n"
            "Qualifications suggérées, à valider par un humain (JSON) :\n"
            + (_lines(qualifs) if qualifs else "aucune") + "\n\n"
            f"Rédige la synthèse : de {MIN_PARAGRAPHS} à {MAX_PARAGRAPHS} paragraphes, dans l'ordre : ce qui bloque "
            "(gravité bloquant), ce qui est à corriger (gravité majeur), ce qui est toléré (gravité mineur et info), "
            "et dans quel ordre s'en occuper. Le premier paragraphe commence exactement par : "
            f"« {opening(self.context['verdict'])} »"
        )
        return LLMRequest(prompt=prompt, schema=SYNTHESIS_SCHEMA, system=self.system, timeout=self.timeout)

    def needed_context(self) -> int:
        """Context for the whole run: the largest request (the synthesis counted with every event
        qualified), plus the answer."""
        widest = self.synthesis({e["n"]: Qualification(max(QUALIFICATIONS, key=len), "") for e in self.qualify})
        biggest = max(_estimate(r) for r in [a.request for a in self.asks] + [widest])
        return -(-(biggest + ANSWER_TOKENS) // CONTEXT_STEP) * CONTEXT_STEP


def _estimate(request: LLMRequest) -> int:
    from PIL import Image

    tokens = TOKENS_PER_CHAR * (len(request.system or "") + len(request.prompt))
    for image in request.images:
        w, h = Image.open(io.BytesIO(image)).size
        tokens += math.ceil(w / IMAGE_PIXELS_PER_TOKEN) * math.ceil(h / IMAGE_PIXELS_PER_TOKEN)
    return math.ceil(tokens)


def _ask(client: LLMClient, request: LLMRequest, ids: tuple[int, ...], kind: str, log: list[dict], parse):
    """Parsed answer, after one retry with a reminder of the schema. LLMError goes through."""
    error = None
    for retry in (False, True):
        r = dataclasses.replace(request, prompt=request.prompt + RETRY_HINT) if retry else request
        entry = {"kind": kind, "anomalies": list(ids), "retry": retry, "images": len(r.images),
                 "request_sha256": request_fingerprint(r.system or "", r.prompt, r.images, r.schema)}
        log.append(entry)
        start = time.perf_counter()
        try:
            raw = client.generate(r)
        except LLMError as exc:
            entry.update(seconds=round(time.perf_counter() - start, 2), error=str(exc), response=None)
            raise
        usage = client.usage()
        entry.update(seconds=round(time.perf_counter() - start, 2),
                     prompt_tokens=usage.prompt_tokens if usage else None,
                     output_tokens=usage.output_tokens if usage else None, response=raw)
        try:
            return parse(raw)
        except (ValueError, KeyError, TypeError) as exc:  # JSONDecodeError is a ValueError
            error = f"{exc.__class__.__name__}: {exc}"
            entry["malformed"] = error
    raise _Malformed(error)


def execute(plan: Plan, client: LLMClient, log: list[dict], progress: Progress | None = None) -> Outcome:
    progress = progress or (lambda _m: None)
    out = Outcome(model=client.model, paragraphs=None, fallback=None, requested=len(plan.qualify),
                  num_ctx=client.num_ctx)
    interrupted = None
    for i, ask in enumerate(plan.asks, start=1):
        if interrupted:
            out.rejected.update({n: interrupted for n in ask.ids})
            continue
        progress(f"IA : qualification {i}/{len(plan.asks)} (anomalie(s) {', '.join(map(str, ask.ids))})")
        try:
            items = _ask(client, ask.request, ask.ids, "qualification", log, _parse_qualifications)
        except LLMError as exc:
            interrupted = f"couche IA interrompue : {exc}"
            out.rejected.update({n: interrupted for n in ask.ids})
            continue
        except _Malformed as exc:
            out.rejected.update({n: f"réponse du modèle mal formée ({exc})" for n in ask.ids})
            continue
        kept, rejected = check_qualifications(items, ask.ids, plan.allowed)
        out.qualifications.update(kept)
        out.rejected.update(rejected)
    if interrupted:
        out.fallback = interrupted
        return out
    progress("IA : synthèse")
    try:
        paragraphs = _ask(client, plan.synthesis(out.qualifications), (), "synthese", log, _parse_synthesis)
    except LLMError as exc:
        out.fallback = f"couche IA interrompue : {exc}"
        return out
    except _Malformed as exc:
        out.fallback = f"réponse du modèle mal formée ({exc})"
        return out
    text = "\n".join(paragraphs)
    problems = verdict_problems(text, plan.context["verdict"]) + text_problems(text, plan.allowed)
    if problems:
        shown = "; ".join(problems[:5]) + (f" (et {len(problems) - 5} autre(s))" if len(problems) > 5 else "")
        out.fallback = f"contrôle de la synthèse en échec : {shown}"
    else:
        out.paragraphs = paragraphs
    return out


# --- llm_synthese.json ---------------------------------------------------------------------------


class _CacheMiss(Exception):
    pass


class _Replay(LLMClient):
    """Answers recorded in llm_synthese.json, by request fingerprint."""

    def __init__(self, model: str, recorded: list[dict]):
        self.model = model
        self.answers = {r["request_sha256"]: r["response"] for r in recorded if r.get("response") is not None}

    def generate(self, request: LLMRequest) -> str:
        key = request_fingerprint(request.system or "", request.prompt, request.images, request.schema)
        if key not in self.answers:
            raise _CacheMiss(key)
        return self.answers[key]


def _read(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("version") == FILE_VERSION else None


def _write(path: Path, plan: Plan, client: LLMClient, out: Outcome, log: list[dict], complete: bool) -> None:
    images = {str(n): hashlib.sha256(plan.images[n]).hexdigest() for n in sorted(plan.images)}
    data = {
        "version": FILE_VERSION,
        "model": client.model,
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": hashlib.sha256(plan.system.encode("utf-8")).hexdigest(),
        "inputs_sha256": plan.inputs_sha256,
        "fingerprint": plan.fingerprint(client.model),
        "options": client.settings(),
        "num_ctx": client.num_ctx,
        "complete": complete,  # False: interrupted (Ollama), never replayed
        "elapsed_seconds": out.elapsed,
        "requests": log,
        "result": {
            "synthese": out.paragraphs,
            "repli": out.fallback,
            "qualifications": {str(n): dataclasses.asdict(q) for n, q in sorted(out.qualifications.items())},
            "videes": {str(n): why for n, why in sorted(out.rejected.items())},
        },
        "inputs": {"context": plan.context, "events": plan.events, "images_sha256": images},
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def _client(options: Options, model: str) -> tuple[LLMClient | None, str | None]:
    if options.client is not None:
        return options.client, None
    try:
        return OllamaClient(model=pick_model(model, OllamaClient().installed())), None
    except LLMError as exc:
        return None, str(exc)


def run(workdir: Path, context: dict, events: list[dict], images: dict[int, Path], options: Options,
        progress: Progress | None = None) -> Outcome:
    """Synthesis and qualifications for the report; never raises because of the model."""
    progress = progress or (lambda _m: None)
    plan = Plan(PROMPT_FILE.read_text(encoding="utf-8"), context, events,
                {n: p.read_bytes() for n, p in images.items()}, options.timeout)
    model = options.client.model if options.client is not None else options.model or DEFAULT_MODEL
    path = workdir / wd.LLM_SYNTHESIS
    stored = None if options.refresh else _read(path)
    if stored and stored.get("complete") and stored.get("fingerprint") == plan.fingerprint(model):
        try:
            out = execute(plan, _Replay(model, stored.get("requests", [])), [])
        except _CacheMiss:
            pass  # recorded answers do not cover this run: ask the model
        else:
            out.reused, out.num_ctx = True, stored.get("num_ctx")
            progress(f"IA : réponses reprises de {wd.LLM_SYNTHESIS} (mêmes entrées, modèle {model})")
            return out
    client, why = _client(options, model)
    if client is None:
        return failed(f"couche IA indisponible : {why}", len(plan.qualify))
    needed = plan.needed_context()
    if client.num_ctx is None:
        if needed > MAX_CONTEXT:
            return failed(f"données trop longues pour le modèle (contexte estimé à {needed} jetons, plus que "
                          f"{MAX_CONTEXT})", len(plan.qualify))
        client.num_ctx = needed
    elif client.num_ctx < needed:
        return failed(f"contexte de {client.num_ctx} jetons trop petit (il en faut {needed})", len(plan.qualify))
    progress(f"IA : modèle {client.model}, contexte {client.num_ctx} jetons, {len(plan.asks) + 1} requête(s)")
    log: list[dict] = []
    start = time.perf_counter()
    try:
        out = execute(plan, client, log, progress)
    finally:
        client.release()  # keep_alive 0: the model leaves the GPU memory
    out.elapsed = round(time.perf_counter() - start, 1)
    out.calls = len(log)
    complete = not any(entry.get("error") for entry in log)
    _write(path, plan, client, out, log, complete)
    return out
