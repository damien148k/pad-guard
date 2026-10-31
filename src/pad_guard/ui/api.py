"""JSON API of the local interface, over the files PAD Guard writes and its Python functions.

Every value shown comes from PAD Guard: the profile files resolved by ``profiles.resolve``, the
JSON of the analysis directories, the functions of the CLI. Nothing here decides a verdict.
"""

from __future__ import annotations

import json
from pathlib import Path

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from pad_guard import llm
from pad_guard.profiles import resolve_profile
from pad_guard.rules.profile import ProfileError
from pad_guard.ui.server import ApiError, Context, ctx_of


def profiles_dir(ctx: Context) -> Path:
    return ctx.root / "profiles"


def list_profiles(ctx: Context) -> list[dict]:
    """Profiles of profiles/*.yaml (not the drafts, not the templates), as their files say."""
    out = []
    for path in sorted(profiles_dir(ctx).glob("*.yaml")):
        item = {"name": path.stem, "file": str(path.relative_to(ctx.root)).replace("\\", "/")}
        try:
            meta = resolve_profile(path).profile.meta
        except ProfileError as exc:
            out.append({**item, "error": "; ".join(exc.messages)})
            continue
        out.append({**item, "name": meta.name, "broadcaster": meta.broadcaster, "version": meta.version,
                    "status": meta.status, "validated_by": meta.validated_by,
                    "validated_at": meta.validated_at.isoformat() if meta.validated_at else None,
                    "source_document": meta.source_document, "source_pdf_sha256": meta.source_pdf_sha256})
    return out


def list_drafts(ctx: Context, profiles: list[dict]) -> list[dict]:
    """Drafts of profiles/drafts/ (draft-profile) and whether a validated profile comes from the same PDF."""
    validated = {p.get("source_pdf_sha256") for p in profiles if p.get("status") == "validated"}
    out = []
    for path in sorted((profiles_dir(ctx) / "drafts").glob("*.findings.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        meta = data.get("meta", {})
        name = path.name.removesuffix(".findings.json")
        sha = meta.get("source_pdf_sha256") or data.get("pdf_sha256")
        out.append({"name": name, "broadcaster": meta.get("broadcaster"), "source_pdf": meta.get("source_pdf"),
                    "source_document": meta.get("source_document"), "pages": data.get("pages"),
                    "source_pdf_sha256": sha, "validated": sha in validated,
                    "draft": str(path.with_name(name + ".yaml").relative_to(ctx.root)).replace("\\", "/")})
    return out


async def get_profiles(request: Request) -> Response:
    ctx = ctx_of(request)
    profiles = list_profiles(ctx)
    return JSONResponse({"profiles": profiles, "drafts": list_drafts(ctx, profiles)})


def llm_models(installed: list[str] | None, error: str | None = None) -> dict:
    """Models of the local AI to choose from before a launch (``ollama list``), and the one preselected:
    DEFAULT_MODEL when installed."""
    installed = installed or []
    selected = llm.DEFAULT_MODEL if llm.DEFAULT_MODEL in installed else (installed[0] if installed else None)
    if error is None and llm.DEFAULT_MODEL not in installed:
        error = f"modèle par défaut absent d'Ollama : lancer « ollama pull {llm.DEFAULT_MODEL} »"
    return {"default": llm.DEFAULT_MODEL, "installed": installed, "selected": selected, "error": error}


async def get_llm_models(request: Request) -> Response:
    try:
        installed = await run_in_threadpool(llm.OllamaClient().installed)
    except llm.LLMError as exc:
        return JSONResponse(llm_models(None, str(exc)))
    return JSONResponse(llm_models(installed))


def model_flag(flag: str, data: dict, key: str = "model") -> list[str]:
    """``[flag, model]`` for the CLI when the page chose a model (the CLI checks that Ollama has it)."""
    model = str(data.get(key) or "").strip()
    if not model:
        return []
    if model.startswith("-") or any(c.isspace() for c in model):
        raise ApiError(f"nom de modèle illisible : {model}")
    return [flag, model]


def routes() -> list:
    from pad_guard.ui import analysis, normes, prepare, review, runs  # noqa: PLC0415

    return [
        *normes.routes(),
        *prepare.routes(),
        *analysis.routes(),
        *runs.routes(),
        *review.routes(),
        Route("/api/profiles", get_profiles),
        Route("/api/llm/models", get_llm_models),
    ]


def start(ctx: Context) -> None:
    """Services of the API: the background jobs."""
    from pad_guard.ui import analysis  # noqa: PLC0415

    analysis.start(ctx)
