"""Profiles tab: a draft from a broadcaster's PDF (``draft-profile`` as a job), then its review.

The review is ``draft.review``, the functions ``review-profile`` uses in the terminal: the same
questions, the same decisions, the same checks before writing. One difference, asked by Vincent's
process: every field needs an explicit decision (no default answer, no « accept all »), and so
does every reference to a norm. Decisions are saved as they are made (``<draft>.review.json``), so
that a closed browser loses nothing. Implausible values and blocking or major rules that would
rest on a norm only are sent with a flag the page shows in red.
"""

from __future__ import annotations

import re
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from pad_guard.draft import pdf as pdf_mod, review
from pad_guard.draft.write import CAPPED, one_line, scalar
from pad_guard.ui.analysis import jobs_of
from pad_guard.ui.api import model_flag
from pad_guard.ui.jobs import snapshot
from pad_guard.ui.server import ApiError, Context, body, ctx_of

GROUPS = {"format": "Format", "video": "Image", "audio": "Audio", "structure": "Structure", "rules": "Règles"}
NAME = re.compile(r"^[a-z0-9][a-z0-9_]{1,60}$")
ANSWER_LABELS = {"a": "Proposition acceptée", "c": "Corrigé", "v": "Laissé vide (hérité d'une norme)",
                 "g": "Valeur du profil de base gardée"}


@dataclass
class Session:
    rv: review.Review
    answers: dict[str, str] = field(default_factory=dict)  # path -> answer given (a, 1, 2, c, v, g)
    references: dict[str, bool] = field(default_factory=dict)  # norm -> confirmed
    fills: dict[str, Any] = field(default_factory=dict)  # required field left missing -> value (None: remove)


_sessions: dict[str, Session] = {}
_lock = threading.Lock()


def draft_paths(ctx: Context, name: str) -> tuple[Path, Path]:
    if not NAME.match(name or ""):
        raise ApiError(f"nom de profil invalide : {name} (minuscules, chiffres et _)")
    drafts = ctx.root / "profiles" / "drafts"
    return drafts / f"{name}.yaml", ctx.root / "profiles" / f"{name}.yaml"


def session(ctx: Context, name: str, fresh: bool = False) -> Session:
    draft, own = draft_paths(ctx, name)
    if not draft.is_file():
        raise ApiError(f"brouillon introuvable : {draft.name}", 404)
    with _lock:
        key = str(draft)
        if fresh or key not in _sessions:
            base = own if own.is_file() else review.TEMPLATE
            try:
                rv = review.load(draft, base)
            except review.ReviewError as exc:
                raise ApiError(str(exc)) from None
            s = Session(rv)
            _restore(s)
            _sessions[key] = s
        return _sessions[key]


def _saved(s: Session) -> Path:
    return s.rv.draft.with_name(s.rv.draft.stem + ".review.json")


def _restore(s: Session) -> None:
    """Decisions made earlier in the interface for this draft (same questions)."""
    import json  # noqa: PLC0415

    path = _saved(s)
    if not path.is_file():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    if "answers" not in data:  # written by the terminal review: not replayed here
        return
    asked = {q.path for q in review.questions(s.rv)[0]}
    s.rv.decisions = [review.Decision(**d) for d in data.get("decisions", []) if d["path"] in asked]
    s.answers = {p: a for p, a in data.get("answers", {}).items() if p in asked}
    s.references = data.get("confirmed", {})
    s.rv.references = data.get("references", [])
    s.fills = data.get("fills", {})


def _save(s: Session) -> None:
    import json  # noqa: PLC0415

    data = {"decisions": [vars(d) for d in s.rv.decisions], "references": s.rv.references, "answers": s.answers,
            "confirmed": s.references, "fills": s.fills}
    _saved(s).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def _finding(x: dict) -> dict:
    return {"value": scalar(x["value"]) if x.get("value") is not None else None, "page": x.get("page"),
            "quote": x.get("quote", ""), "status": x.get("status"), "reason": x.get("reason") or "",
            "implausible": x.get("status") == review.IMPLAUSIBLE}


def question_view(s: Session, q: review.Question) -> dict:
    decision = next((d for d in s.rv.decisions if d.path == q.path), None)
    norm_value = scalar(q.norm[0]) if q.norm else None
    shown = scalar(q.value) if q.value is not None else None
    return {
        "path": q.path, "description": q.description, "group": GROUPS.get(q.path.split(".")[0], "Autres"),
        "status": q.status, "implausible": q.implausible,
        "value": shown, "proposal": _finding(q.proposal) if q.proposal else None,
        "reference": _finding(q.reference) | {"norm": q.reference.get("norm")} if q.reference else None,
        "rejected": [_finding(x) for x in q.rejected],
        "candidates": [{"n": k, **_finding(q.findings[k - 1])} for k in q.candidates],
        "findings": [_finding(x) for x in q.findings],
        "base_value": scalar(q.base_value) if q.base_value is not None else None,
        "norm": {"value": norm_value, "title": q.norm[1]} if q.norm else None,
        # Information only (principle 2): the client's value applies even when a norm says otherwise.
        "differs_from_norm": bool(q.norm and shown is not None and norm_value != shown),
        "choices": q.choices,
        "answer": s.answers.get(q.path),
        "answer_label": (ANSWER_LABELS.get(s.answers[q.path], f"Candidat {s.answers[q.path]} choisi")
                         if q.path in s.answers else None),
        "decision": {"action": decision.action, "value": scalar(decision.value) if decision.value is not None else None,
                     "source": decision.source} if decision else None,
    }


def review_view(ctx: Context, s: Session) -> dict:
    rv = s.rv
    asked, skipped = review.questions(rv)
    refs = review.reference_questions(rv)
    data = {}
    try:
        import json  # noqa: PLC0415

        data = json.loads(rv.draft.with_name(rv.draft.stem + ".findings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    _, own = draft_paths(ctx, rv.meta["name"])
    return {
        "name": rv.meta["name"], "broadcaster": rv.meta.get("broadcaster"), "source_document": rv.meta.get("source_document"),
        "source_pdf": rv.meta.get("source_pdf"), "pages": data.get("pages"), "model": data.get("model"),
        "base": rv.base.name, "out": str(own.relative_to(ctx.root)).replace("\\", "/"), "out_exists": own.is_file(),
        "capped": {"pages": rv.capped_pages, "message": CAPPED},
        "questions": [question_view(s, q) for q in asked],
        "skipped": [f["path"] for f in skipped],
        "references": [{"norm": r.norm, "title": r.title, "page": r.page, "quote": one_line(r.quote, 300),
                        "values": [[p, one_line(scalar(v), 60)] for p, v in r.values],
                        "confirmed": s.references.get(r.norm)} for r in refs],
        "fills": s.fills,
        "pdf_available": _pdf_path(ctx, rv) is not None,
    }


def _pdf_path(ctx: Context, rv: review.Review) -> Path | None:
    shown = rv.meta.get("source_pdf")
    if not shown:
        return None
    path = Path(shown)
    for candidate in (path, ctx.root / path, review.ROOT / path):
        if candidate.is_file():
            return candidate
    return None


def _question(s: Session, path: str) -> review.Question:
    q = next((q for q in review.questions(s.rv)[0] if q.path == path), None)
    if q is None:
        raise ApiError(f"champ absent de la relecture : {path}", 404)
    return q


def build_profile(s: Session) -> tuple[dict, dict]:
    data, comments = review.build(s.rv)
    doc = s.rv.meta.get("source_document", "document")
    for path, value in s.fills.items():
        if path.rsplit(".", 1)[0] and review.missing_section(data, path) is not None:
            review.fill_missing(data, comments, path, value, doc)
    return data, comments


def check(ctx: Context, s: Session) -> dict:
    """Everything decided? Then the profile is written aside and checked (missing fields, risks)."""
    asked, _ = review.questions(s.rv)
    pending = [q.path for q in asked if q.path not in s.answers]
    refs = [r.norm for r in review.reference_questions(s.rv) if r.norm not in s.references]
    out = {"pending": pending, "pending_references": refs, "missing": [], "risks": [], "unsourced": 0, "ready": False}
    if pending or refs:
        return out
    data, comments = build_profile(s)
    review.validate(data, "(validation en cours)")
    _, own = draft_paths(ctx, s.rv.meta["name"])
    try:
        resolved, tmp = review.write(s.rv, own, data, comments)
    except review.ReviewError as exc:
        missing = review.missing_fields(exc)
        if not missing:
            raise ApiError(str(exc)) from None
        from pad_guard.draft.schema import catalogue  # noqa: PLC0415

        specs = {x.path: x for x in catalogue()}
        out["missing"] = [{"path": p, "section": review.missing_section(data, p), "description": specs[p].description
                           if p in specs else ""} for p in missing]
        return out
    tmp.unlink(missing_ok=True)
    out["risks"] = review.norm_only_rules(resolved)
    out["unsourced"] = sum(1 for c in comments.values() if c.startswith("A VERIFIER"))
    out["ready"] = True
    return out


# --- routes -------------------------------------------------------------------------------

async def get_review(request: Request) -> Response:
    ctx = ctx_of(request)
    s = session(ctx, request.path_params["name"], fresh=request.query_params.get("fresh") == "1")
    return JSONResponse(review_view(ctx, s))


async def decide(request: Request) -> Response:
    ctx = ctx_of(request)
    s = session(ctx, request.path_params["name"])
    data = await body(request)
    q = _question(s, str(data.get("path") or ""))
    answer = str(data.get("answer") or "")
    correction = None
    if answer == "c":
        text = str(data.get("value") or "").strip()
        if not text:
            raise ApiError("valeur corrigée vide")
        try:
            value = yaml.safe_load(text)
        except yaml.YAMLError:
            raise ApiError("valeur illisible (YAML attendu, ex. -23 ou [\"25/1\"])") from None
        try:
            correction = review.corrected(s.rv, q.path, value, str(data.get("page") or ""), str(data.get("quote") or ""))
        except review.ReviewError as exc:
            raise ApiError(str(exc)) from None
    try:
        review.decide(s.rv, q, answer, correction)
    except review.ReviewError as exc:
        raise ApiError(str(exc)) from None
    s.answers[q.path] = answer
    _save(s)
    return JSONResponse(question_view(s, q))


async def reset(request: Request) -> Response:
    """« Rétablir l'extraction »: the field goes back to « à vérifier »."""
    ctx = ctx_of(request)
    s = session(ctx, request.path_params["name"])
    data = await body(request)
    q = _question(s, str(data.get("path") or ""))
    s.rv.decisions = [d for d in s.rv.decisions if d.path != q.path]
    s.answers.pop(q.path, None)
    _save(s)
    return JSONResponse(question_view(s, q))


async def reference(request: Request) -> Response:
    ctx = ctx_of(request)
    s = session(ctx, request.path_params["name"])
    data = await body(request)
    rq = next((r for r in review.reference_questions(s.rv) if r.norm == data.get("norm")), None)
    if rq is None:
        raise ApiError(f"renvoi inconnu : {data.get('norm')}", 404)
    confirmed = bool(data.get("confirmed"))
    review.confirm_reference(s.rv, rq, confirmed)
    s.references[rq.norm] = confirmed
    _save(s)
    return JSONResponse(review_view(ctx, s))


async def fill(request: Request) -> Response:
    ctx = ctx_of(request)
    s = session(ctx, request.path_params["name"])
    data = await body(request)
    path = str(data.get("path") or "")
    text = data.get("value")
    if text in (None, ""):
        value = None
    else:
        try:
            value = yaml.safe_load(str(text))
        except yaml.YAMLError:
            raise ApiError("valeur illisible (YAML attendu)") from None
        trial: dict = {"sources": {}}
        try:
            review.fill_missing(trial, {}, path, value, "document")
        except review.ReviewError as exc:
            raise ApiError(str(exc)) from None
    s.fills[path] = value
    _save(s)
    return JSONResponse(check(ctx, s))


async def get_check(request: Request) -> Response:
    ctx = ctx_of(request)
    return JSONResponse(check(ctx, session(ctx, request.path_params["name"])))


async def validate(request: Request) -> Response:
    ctx = ctx_of(request)
    s = session(ctx, request.path_params["name"])
    data = await body(request)
    who = " ".join(str(data.get("who") or "").split())
    if not who:
        raise ApiError("nom du validateur vide")
    state = check(ctx, s)
    if not state["ready"]:
        raise ApiError("relecture incomplète : " + ", ".join(state["pending"] + state["pending_references"]
                                                            + [m["path"] for m in state["missing"]]))
    if state["risks"] and not data.get("confirm_risks"):
        raise ApiError("règles bloquantes ou majeures plafonnées par une norme : confirmation explicite requise")
    _, own = draft_paths(ctx, s.rv.meta["name"])
    if own.is_file() and not data.get("overwrite"):
        raise ApiError(f"{own.name} existe : confirmer son remplacement", 409)
    built, comments = build_profile(s)
    review.validate(built, who)
    resolved, tmp = review.write(s.rv, own, built, comments)
    review.finish(tmp, own)
    with _lock:
        _sessions.pop(str(s.rv.draft), None)
    meta = resolved.profile.meta
    return JSONResponse({"name": meta.name, "version": meta.version, "file": str(own.relative_to(ctx.root)).replace("\\", "/"),
                         "validated_by": meta.validated_by, "validated_at": meta.validated_at.isoformat(),
                         "fingerprint": resolved.fingerprint})


async def page(request: Request) -> Response:
    from starlette.concurrency import run_in_threadpool  # noqa: PLC0415

    ctx = ctx_of(request)
    s = session(ctx, request.path_params["name"])
    path = _pdf_path(ctx, s.rv)
    if path is None:
        raise ApiError("PDF du brouillon introuvable (diffuseurs/)", 404)
    n = int(request.path_params["n"])
    png = await run_in_threadpool(pdf_mod.render, path, n, 1.5)
    return Response(png, media_type="image/png")


async def highlight(request: Request) -> Response:
    """Boxes of a quote on its page (fractions of the page), for the highlight on the preview."""
    from starlette.concurrency import run_in_threadpool  # noqa: PLC0415

    ctx = ctx_of(request)
    s = session(ctx, request.path_params["name"])
    path = _pdf_path(ctx, s.rv)
    if path is None:
        raise ApiError("PDF du brouillon introuvable (diffuseurs/)", 404)
    try:
        n = int(request.query_params.get("page") or 0)
    except ValueError:
        raise ApiError("numéro de page illisible") from None
    boxes = await run_in_threadpool(pdf_mod.quote_boxes, path, n, request.query_params.get("quote") or "")
    return JSONResponse({"boxes": [dict(zip(("x0", "top", "x1", "bottom"), b)) for b in boxes], "found": bool(boxes)})


async def start_draft(request: Request) -> Response:
    """draft-profile as a job; the PDF is copied into diffuseurs/ (inventory of the documents)."""
    ctx = ctx_of(request)
    data = await body(request)
    name = str(data.get("name") or "").strip()
    draft, _ = draft_paths(ctx, name)
    model = model_flag("--model", data)
    src = Path(str(data.get("pdf") or "").strip().strip('"'))
    if not src.is_absolute() or not src.is_file() or src.suffix.lower() != ".pdf":
        raise ApiError(f"PDF introuvable : {src}")
    inventory = ctx.root / "diffuseurs"
    inventory.mkdir(exist_ok=True)
    pdf = src
    if not src.resolve().is_relative_to(inventory.resolve()):
        pdf = inventory / src.name
        if pdf.exists() and pdf_mod.sha256(pdf) != pdf_mod.sha256(src):
            raise ApiError(f"un autre document porte déjà ce nom dans diffuseurs/ : {src.name}")
        if not pdf.exists():
            shutil.copyfile(src, pdf)
    args = ["draft-profile", str(pdf), "--name", name, "--out-dir", str(draft.parent), *model]
    if data.get("broadcaster"):
        args += ["--broadcaster", str(data["broadcaster"]).strip()]
    job = jobs_of(ctx).start("draft", f"Brouillon {name} · {pdf.name}", args, draft.parent / f"{name}.progression.jsonl")
    return JSONResponse(snapshot(job))


def routes() -> list:
    return [
        Route("/api/jobs/draft", start_draft, methods=["POST"]),
        Route("/api/drafts/{name}/review", get_review),
        Route("/api/drafts/{name}/decision", decide, methods=["PUT"]),
        Route("/api/drafts/{name}/decision/reset", reset, methods=["POST"]),
        Route("/api/drafts/{name}/reference", reference, methods=["POST"]),
        Route("/api/drafts/{name}/missing", fill, methods=["POST"]),
        Route("/api/drafts/{name}/check", get_check),
        Route("/api/drafts/{name}/validate", validate, methods=["POST"]),
        Route("/api/drafts/{name}/page/{n:int}", page),
        Route("/api/drafts/{name}/highlight", highlight),
    ]
