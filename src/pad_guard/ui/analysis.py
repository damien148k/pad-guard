"""Launching and following an analysis from the interface: the arguments of ``pad-guard analyze``.

The checks before launching are those of the CLI (``audio_map.parse``, ``pipeline.preflight``);
the analysis directory is ``<analyses root>/<film>_<AAAAMMJJ-HHMM>``.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import subprocess
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from pad_guard import audio_map as amap, pipeline, workdir as wd
from pad_guard.ui.jobs import JobManager, snapshot
from pad_guard.ui.prepare import load_resolved, master_info
from pad_guard.ui.server import ApiError, Context, body, ctx_of

STREAM_INTERVAL = 0.5


def jobs_of(ctx: Context) -> JobManager:
    return ctx.extra["jobs"]


def new_workdir(root: Path, film: Path, when: dt.datetime | None = None) -> Path:
    stamp = (when or dt.datetime.now()).strftime("%Y%m%d-%H%M")
    base = root / f"{film.stem}_{stamp}"
    path, n = base, 2
    while path.exists():
        path, n = base.with_name(f"{base.name}-{n}"), n + 1
    return path


def analyze_plan(ctx: Context, data: dict) -> dict:
    master = master_info(str(data.get("master") or ""))
    name = str(data.get("profile") or "")
    path, resolved = load_resolved(ctx, name)
    prof = resolved.profile
    spec = data.get("audio_map") or None
    try:
        mapping = amap.parse(spec, prof) if spec else amap.from_profile(prof)
    except amap.AudioMapError as exc:
        raise ApiError(str(exc)) from None
    workdir = new_workdir(ctx.settings().root, Path(master["path"]))
    args = ["analyze", master["path"], "--profile", str(path), "--out", str(workdir),
            *(["--audio-map", spec] if spec else []), *(["--llm", "ollama"] if data.get("llm") else [])]
    return {"args": args, "command": subprocess.list2cmdline(["pad-guard", *args]), "workdir": str(workdir),
            "run_id": workdir.name, "title": f"{master['name']} · {prof.meta.name} v{prof.meta.version}",
            "problems": pipeline.preflight(prof, mapping.groups)}


async def preview(request: Request) -> Response:
    plan = analyze_plan(ctx_of(request), await body(request))
    return JSONResponse({k: plan[k] for k in ("command", "workdir", "problems")})


async def launch(request: Request) -> Response:
    ctx = ctx_of(request)
    plan = analyze_plan(ctx, await body(request))
    if plan["problems"]:
        raise ApiError("profil incomplet pour cette analyse : " + " ; ".join(plan["problems"]))
    workdir = Path(plan["workdir"])
    workdir.mkdir(parents=True, exist_ok=False)
    job = jobs_of(ctx).start("analyze", plan["title"], plan["args"], workdir / wd.PROGRESS, workdir, plan["run_id"])
    return JSONResponse(snapshot(job))


async def current(request: Request) -> Response:
    job = jobs_of(ctx_of(request)).current()
    return JSONResponse(snapshot(job) if job else None)


async def cancel(request: Request) -> Response:
    job = jobs_of(ctx_of(request)).cancel()
    return JSONResponse(snapshot(job) if job else None)


async def events(request: Request) -> Response:
    """Server-sent events: the job screen at each change, until the job ends."""
    jobs = jobs_of(ctx_of(request))

    async def stream():
        last = None
        while not await request.is_disconnected():
            job = jobs.current()
            data = json.dumps(snapshot(job) if job else None, ensure_ascii=False)
            if data != last:
                yield f"data: {data}\n\n"
                last = data
            if job is None or job.state != "running":
                break
            await asyncio.sleep(STREAM_INTERVAL)

    return StreamingResponse(stream(), media_type="text/event-stream")


def routes() -> list:
    return [
        Route("/api/jobs/analyze/preview", preview, methods=["POST"]),
        Route("/api/jobs/analyze", launch, methods=["POST"]),
        Route("/api/jobs/current", current),
        Route("/api/jobs/current/events", events),
        Route("/api/jobs/current/cancel", cancel, methods=["POST"]),
    ]


def start(ctx: Context) -> None:
    ctx.extra.setdefault("jobs", JobManager(ctx.settings_file.parent / "taches"))
