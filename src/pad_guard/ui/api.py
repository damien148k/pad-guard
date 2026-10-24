"""JSON API of the local interface, over the files PAD Guard writes and its Python functions.

Every value shown comes from PAD Guard: the profile files resolved by ``profiles.resolve``, the
JSON of the analysis directories, the functions of the CLI. Nothing here decides a verdict.
"""

from __future__ import annotations

import json
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from pad_guard.profiles import resolve_profile
from pad_guard.rules.profile import ProfileError
from pad_guard.ui.server import Context, ctx_of


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


def routes() -> list:
    from pad_guard.ui import analysis, prepare  # noqa: PLC0415

    return [
        *prepare.routes(),
        *analysis.routes(),
        Route("/api/profiles", get_profiles),
    ]


def start(ctx: Context) -> None:
    """Services of the API: the background jobs."""
    from pad_guard.ui import analysis  # noqa: PLC0415

    analysis.start(ctx)
