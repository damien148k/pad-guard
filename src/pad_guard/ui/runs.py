"""Analyses already made (folders of the analyses root) and the « Rapport » screen.

The report screen is ``rapport.json``, written by the report step from the same sections as
rapport.md: the page shows exactly what the PDF says. Anomalies are named by ``Event.key``
(type@frame@group), never by their rank, for the links and the thumbnails.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
from pathlib import Path

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from pad_guard import workdir as wd
from pad_guard.labels import status_label
from pad_guard.ui.analysis import jobs_of
from pad_guard.ui.jobs import snapshot
from pad_guard.ui.server import ApiError, Context, body, ctx_of

RERUN_PROGRESS = "progression_relance.jsonl"
FILES = {"rapport.pdf": wd.REPORT_PDF, "rapport.md": wd.REPORT_MD, "luminance.png": f"{wd.CHARTS}/luminance.png",
         "loudness.png": f"{wd.CHARTS}/loudness.png"}


def _date(text: str | None) -> str:
    if not text:
        return "date inconnue"
    try:
        return dt.datetime.fromisoformat(text).strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return text


def _duration(start: str | None, end: str | None) -> str | None:
    try:
        seconds = int((dt.datetime.fromisoformat(end) - dt.datetime.fromisoformat(start)).total_seconds())
    except (TypeError, ValueError):
        return None
    if seconds >= 3600:
        return f"{seconds // 3600} h {seconds % 3600 // 60:02d} min"
    return f"{seconds // 60} min {seconds % 60:02d} s"


def tone(verdict: dict | None) -> str:
    """Colour of a verdict written by the rules: green CONFORME, red NON-CONFORME, amber indicative."""
    if not verdict:
        return "none"
    if verdict.get("indicative"):
        return "draft"
    return "ok" if verdict.get("status") == "CONFORME" else "nc"


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def run_dir(ctx: Context, run_id: str) -> Path:
    root = ctx.settings().root
    if not run_id or run_id in (".", "..") or "/" in run_id or "\\" in run_id or ":" in run_id:
        raise ApiError(f"analyse inconnue : {run_id}", 404)
    path = root / run_id
    if not (path / wd.RUN).is_file():
        raise ApiError(f"analyse introuvable dans {root} : {run_id}", 404)
    return path


def run_item(path: Path, root: Path) -> dict:
    run = _read(path / wd.RUN) or {}
    verdict = _read(path / wd.VERDICT)
    probe = _read(path / wd.PROBE) or {}
    ui_job = _read(path / "ui_job.json") or {}
    prof = (verdict or probe).get("profile") or {}
    if verdict:
        label = status_label(verdict["status"], verdict.get("indicative", False))
    else:
        label = {"running": "en cours", "cancelled": "annulée", "failed": "échec"}.get(ui_job.get("state"), "incomplète")
    source = (probe.get("source") or {}).get("path")
    return {"id": path.name, "root": str(root), "workdir": str(path),
            "file_name": Path(source).name if source else path.name,
            "profile": f"{prof.get('name', '?')} v{prof.get('version', '?')}" if prof else "?",
            "analyzed_at": run.get("analyzed_at"), "analyzed_at_text": _date(run.get("analyzed_at")),
            "label": label, "tone": tone(verdict), "has_report": (path / wd.REPORT_JSON).is_file()}


def list_runs(ctx: Context) -> list[dict]:
    root = ctx.settings().root
    if not root.is_dir():
        return []
    items = [run_item(p, root) for p in root.iterdir() if p.is_dir() and (p / wd.RUN).is_file()]
    return sorted(items, key=lambda r: r["analyzed_at"] or "", reverse=True)


def report_view(ctx: Context, run_id: str) -> dict:
    path = run_dir(ctx, run_id)
    item = run_item(path, ctx.settings().root)
    view = _read(path / wd.REPORT_JSON)
    run = _read(path / wd.RUN) or {}
    if view is None:
        return {"run": item, "report": None,
                "missing": "rapport.json absent (analyse incomplète, ou faite avant l'interface) : régénérer le rapport."}
    v = view["verdict"]
    return {
        "run": {**item, "duration": _duration(run.get("analyzed_at"), run.get("finished_at")),
                "reruns": run.get("reruns", [])[-3:],
                "files": {name: (path / rel).is_file() for name, rel in FILES.items()}},
        "report": view,
        "tone": tone(v),
    }


def _thumbnail(ctx: Context, run_id: str, key: str) -> Path:
    path = run_dir(ctx, run_id)
    view = _read(path / wd.REPORT_JSON) or {}
    if key in view.get("duplicate_keys", []):
        raise ApiError(f"plusieurs anomalies portent la clé {key} : vignette ambiguë, voir le rapport PDF", 409)
    event = next((e for e in view.get("events", []) if e["key"] == key), None)
    if event is None:
        raise ApiError(f"anomalie inconnue : {key}", 404)
    if not event.get("thumbnail") or not (path / event["thumbnail"]).is_file():
        raise ApiError(f"pas de vignette pour {key}", 404)
    return path / event["thumbnail"]


def open_folder(path: Path) -> None:
    if os.name == "nt":
        os.startfile(path)  # noqa: S606 - the analysis folder, in the Explorer of this machine
    else:
        subprocess.run(["xdg-open", str(path)], check=False)


# --- routes -------------------------------------------------------------------------------

async def runs(request: Request) -> Response:
    return JSONResponse({"runs": list_runs(ctx_of(request))})


async def report(request: Request) -> Response:
    return JSONResponse(report_view(ctx_of(request), request.path_params["run"]))


async def thumbnail(request: Request) -> Response:
    return FileResponse(_thumbnail(ctx_of(request), request.path_params["run"], request.path_params["key"]))


async def file(request: Request) -> Response:
    name = request.path_params["name"]
    if name not in FILES:
        raise ApiError(f"fichier non servi : {name}", 404)
    path = run_dir(ctx_of(request), request.path_params["run"]) / FILES[name]
    if not path.is_file():
        raise ApiError(f"{name} absent de l'analyse", 404)
    if request.query_params.get("download"):
        stem = request.path_params["run"]
        return FileResponse(path, filename=f"{stem}_{name}", content_disposition_type="attachment")
    return FileResponse(path)


async def rerun(request: Request) -> Response:
    ctx = ctx_of(request)
    data = await body(request)
    run_id = request.path_params["run"]
    path = run_dir(ctx, run_id)
    step = data.get("from") or "rules"
    if step not in ("rules", "report"):
        raise ApiError("étape de relance inconnue (rules ou report)")
    args = ["rerun", str(path), "--from", step, *(["--llm", "ollama"] if data.get("llm") else [])]
    title = f"{run_item(path, ctx.settings().root)['file_name']} · relance depuis « {step} »"
    job = jobs_of(ctx).start("rerun", title, args, path / RERUN_PROGRESS, path, run_id)
    return JSONResponse(snapshot(job))


async def folder(request: Request) -> Response:
    ctx = ctx_of(request)
    path = run_dir(ctx, request.path_params["run"])
    ctx.extra.get("opener", open_folder)(path)
    return JSONResponse({"opened": str(path)})


def routes() -> list:
    return [
        Route("/api/runs", runs),
        Route("/api/runs/{run}/report", report),
        Route("/api/runs/{run}/thumb/{key}", thumbnail),
        Route("/api/runs/{run}/file/{name}", file),
        Route("/api/runs/{run}/rerun", rerun, methods=["POST"]),
        Route("/api/runs/{run}/open-folder", folder, methods=["POST"]),
    ]
