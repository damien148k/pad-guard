"""Screens « Dépôt » and « Récapitulatif »: files chosen by path, profile, format preview, audio map.

The films never go through the browser (up to 120 GB): the server opens the native Windows file
dialog and the page only ever gets a path. The format preview is ``probe_file`` without the
SHA-256 of the source (read by the analysis itself); the audio map is checked by ``audio_map``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from pad_guard import audio_map as amap, timecode
from pad_guard.audio_map import describe, tracks_text
from pad_guard.draft import pdf as pdf_mod
from pad_guard.draft.write import scalar
from pad_guard.labels import number
from pad_guard.probe import ProbeError, probe_file
from pad_guard.profiles import ResolvedProfile, resolve_profile
from pad_guard.profiles.resolve import leaves
from pad_guard.rules.profile import ProfileError
from pad_guard.ui.server import ApiError, Context, body, ctx_of

MASTER_TYPES = (".mov", ".mxf")

# Run in a separate process: Tk must own the main thread of its process, the server's is uvicorn's.
PICK_SCRIPT = r"""
import json, sys, tkinter as tk
from tkinter import filedialog
kind, initial, title = sys.argv[1:4]
root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)
if kind == "folder":
    path = filedialog.askdirectory(parent=root, initialdir=initial or None, title=title, mustexist=False)
else:
    types = ([("Masters ProRes / DNxHR", "*.mov *.mxf"), ("Tous les fichiers", "*.*")] if kind == "master"
             else [("PDF", "*.pdf"), ("Tous les fichiers", "*.*")])
    path = filedialog.askopenfilename(parent=root, initialdir=initial or None, title=title, filetypes=types)
root.destroy()
print(json.dumps(path or None))
"""
PICK_TITLES = {"master": "Choisir le film master", "pdf": "Choisir le cahier des charges du diffuseur (PDF)",
               "folder": "Choisir le dossier des analyses"}


def native_pick(kind: str, initial: str) -> str | None:
    """Path chosen in the native file dialog, None if cancelled."""
    done = subprocess.run([sys.executable, "-I", "-c", PICK_SCRIPT, kind, initial, PICK_TITLES[kind]],
                          capture_output=True, text=True, encoding="utf-8", timeout=3600, check=False)
    if done.returncode != 0:
        raise ApiError("boîte de dialogue impossible à ouvrir : saisir le chemin à la main")
    return json.loads(done.stdout.strip() or "null")


def size_text(size: int) -> str:
    return f"{number(size / 1e9, 1)} Go" if size >= 1e8 else f"{number(size / 1e6, 1)} Mo"


def profile_path(ctx: Context, name: str) -> Path:
    path = ctx.root / "profiles" / f"{name}.yaml"
    if not name or "/" in name or "\\" in name or not path.is_file():
        raise ApiError(f"profil inconnu : {name}")
    return path


def load_resolved(ctx: Context, name: str) -> tuple[Path, ResolvedProfile]:
    path = profile_path(ctx, name)
    try:
        return path, resolve_profile(path)
    except ProfileError as exc:
        raise ApiError(f"profil invalide ({path.name}) : " + " ; ".join(exc.messages)) from None


def master_info(path_text: str) -> dict:
    path = Path(path_text.strip().strip('"'))
    if not path.is_absolute():
        raise ApiError(f"chemin complet attendu : {path_text}")
    if not path.is_file():
        raise ApiError(f"fichier introuvable : {path}")
    return {"path": str(path), "name": path.name, "size_bytes": path.stat().st_size,
            "size": size_text(path.stat().st_size), "supported_extension": path.suffix.lower() in MASTER_TYPES}


# --- profile summary (recap) ----------------------------------------------------------------

def _ref(resolved: ResolvedProfile, path: str) -> str:
    """Short source of a value: the paragraph of the client, or the norm it comes from."""
    o = resolved.origins.get(path)
    if o is None:
        return ""
    if o.source:
        return o.source.split(" : ")[0]
    return o.file


REQUIREMENTS = [  # (label, paths shown together) - a choice of display, the values are the profile's
    ("Codecs du master", ["format.codecs"]),
    ("Image", ["format.width", "format.height", "format.fps_allowed"]),
    ("Livraison", ["format.delivery.scan", "format.delivery.fps", "format.delivery.codec"]),
    ("Timecode du programme", ["structure.timecode.program_start"]),
    ("Amorces", ["structure.leaders"]),
    ("Loudness intégrée", ["audio.loudness.long.integrated_lufs", "audio.loudness.long.integrated_tolerance_lu"]),
    ("True peak", ["audio.true_peak_max_dbtp"]),
    ("Plage de loudness (LRA)", ["audio.loudness.long.lra_max_lu"]),
    ("Luminance tolérée", ["video.y_tolerance_low_pct", "video.y_tolerance_high_pct"]),
]


def _show(value: Any) -> str:
    if isinstance(value, float):
        return number(value, 1)
    if isinstance(value, list):
        return ", ".join(_show(v) for v in value)
    return scalar(value) if not isinstance(value, str) else value


def requirements(resolved: ResolvedProfile) -> list[dict]:
    flat = dict(leaves(resolved.values))
    p = resolved.profile
    rows = []
    for label, paths in REQUIREMENTS:
        present = [x for x in paths if flat.get(x) is not None]
        if not present:
            rows.append({"label": label, "value": "non renseigné", "ref": "A VERIFIER", "paths": paths})
            continue
        if paths[0] == "format.width":
            value = f"{flat.get('format.width')} × {flat.get('format.height')} · {_show(flat.get('format.fps_allowed'))} i/s"
        elif paths[0] == "audio.loudness.long.integrated_lufs":
            value = f"{_show(flat[paths[0]])} LUFS ± {_show(flat.get(paths[1]))} LU"
        elif paths[0] == "audio.true_peak_max_dbtp":
            value = f"≤ {_show(flat[paths[0]])} dBTP"
        elif paths[0] == "audio.loudness.long.lra_max_lu":
            value = f"≤ {_show(flat[paths[0]])} LU"
        elif paths[0] == "video.y_tolerance_low_pct":
            value = f"{_show(flat.get(paths[0]))} % à {_show(flat.get(paths[1]))} %"
        else:
            value = " · ".join(_show(flat[x]) for x in present)
        refs = list(dict.fromkeys(r for r in (_ref(resolved, x) for x in present) if r))
        rows.append({"label": label, "value": value, "ref": " ; ".join(refs), "paths": paths})
    rows.append({"label": "Groupes audio", "value": describe(p.audio.groups) if p.audio.groups else "non renseigné",
                 "ref": _ref(resolved, "audio.groups"), "paths": ["audio.groups"]})
    return rows


def profile_summary(ctx: Context, name: str) -> dict:
    path, resolved = load_resolved(ctx, name)
    meta = resolved.profile.meta
    norms = [layer.document.split(" — ")[0] for layer in resolved.layers if layer.kind == "norm"]
    return {
        "name": meta.name, "file": str(path.relative_to(ctx.root)).replace("\\", "/"), "broadcaster": meta.broadcaster,
        "version": meta.version, "status": meta.status, "validated_by": meta.validated_by,
        "validated_at": meta.validated_at.isoformat() if meta.validated_at else None,
        "source_document": meta.source_document, "norms": norms, "requirements": requirements(resolved),
        "groups": [{"name": g.name, "tracks": g.tracks, "layout": g.layout, "required": g.required}
                   for g in resolved.profile.audio.groups],
    }


# --- probe preview ------------------------------------------------------------------------

def probe_preview(ctx: Context, master: str, profile: str) -> dict:
    info = master_info(master)
    path, resolved = load_resolved(ctx, profile)
    try:
        r = probe_file(info["path"], resolved.profile, path, hash_source=False)
    except ProbeError as exc:
        raise ApiError(f"fichier refusé : {exc}") from None
    v = r.video
    fps = Fraction(v.r_frame_rate) if v.r_frame_rate and v.r_frame_rate != "0/0" else None
    duration = (timecode.from_frames(v.nb_frames, round(fps)) if fps and v.nb_frames else
                f"{number(r.container.duration_s or 0, 2)} s")
    rate = f"{number(float(fps), 3).rstrip('0').rstrip(',')} i/s ({v.r_frame_rate})" if fps else v.r_frame_rate
    colour = " · ".join(x or "non renseigné" for x in (v.color_primaries, v.color_transfer, v.color_space, v.color_range))
    streams = r.audio_streams
    rates = sorted({f"{number(s.sample_rate / 1000, 1)} kHz" for s in streams if s.sample_rate})
    depths = sorted({f"{s.bit_depth} bits" for s in streams if s.bit_depth})
    audio = (f"{len(r.audio_tracks)} piste(s) dans {len(streams)} flux · {', '.join(rates) or '?'} · {', '.join(depths) or '?'}"
             if streams else "aucune piste audio")
    codec = f"{v.codec_name} {v.profile or ''}".strip()
    return {
        "master": info,
        "accepted": r.accepted, "refusal_reasons": r.refusal_reasons,
        "key_cells": [["Conteneur", r.container.kind.upper()], ["Codec", codec],
                      ["Résolution", f"{v.width} × {v.height} · {rate}"], ["Durée", duration]],
        "rows": [["Fichier", info["name"]], ["Taille", info["size"]], ["Conteneur", r.container.format_name],
                 ["Codec vidéo", codec], ["Échantillonnage", v.pix_fmt or "?"], ["Résolution", f"{v.width} × {v.height}"],
                 ["Cadence", rate], ["Balayage (drapeau)", v.field_order or "absent"], ["Colorimétrie", colour],
                 ["Durée", f"{duration} ({v.nb_frames} images)" if v.nb_frames else duration],
                 ["Timecode de départ", f"{r.timecode} ({r.timecode_source})" if r.timecode else "absent"],
                 ["Audio", audio]],
        "checks": [{"label": c.label, "expected": c.expected, "actual": c.actual, "status": c.status} for c in r.checks],
        "tracks": [t.track for t in r.audio_tracks],
    }


# --- audio map ----------------------------------------------------------------------------

def audio_map_for(ctx: Context, profile: str, assign: dict[str, str | None], tracks: int) -> dict:
    """--audio-map built from the group chosen for each track; None when it is the profile's own map."""
    _, resolved = load_resolved(ctx, profile)
    prof = resolved.profile
    names = [g.name for g in prof.audio.groups]
    by_group: dict[str, list[int]] = {}
    for key, group in assign.items():
        if group in (None, "", "—"):
            continue
        if group not in names:
            raise ApiError(f"groupe inconnu du profil : {group}")
        track = int(key)
        if not 1 <= track <= tracks:
            raise ApiError(f"piste {track} absente du fichier ({tracks} piste(s))")
        by_group.setdefault(group, []).append(track)
    if not by_group:
        raise ApiError("aucune piste attribuée à un groupe")
    ordered = [n for n in names if n in by_group]
    spec = ",".join(f"{n}:{tracks_text(sorted(by_group[n]))}" for n in ordered)
    try:
        mapping = amap.parse(spec, prof)
    except amap.AudioMapError as exc:
        raise ApiError(str(exc)) from None
    default = amap.from_profile(prof)
    same = [(g.name, g.tracks, g.layout) for g in mapping.groups] == [(g.name, g.tracks, g.layout) for g in default.groups]
    missing = [g.name for g in prof.audio.groups if g.required and g.name not in by_group]
    return {"spec": None if same else spec, "shown": spec, "describe": describe(mapping.groups),
            "missing_required": missing}


def default_assign(ctx: Context, profile: str, tracks: int) -> dict[str, str | None]:
    _, resolved = load_resolved(ctx, profile)
    out: dict[str, str | None] = {str(t): None for t in range(1, tracks + 1)}
    for g in resolved.profile.audio.groups:
        for t in g.tracks:
            if t <= tracks:
                out[str(t)] = g.name
    return out


# --- PDF of a broadcaster -----------------------------------------------------------------

def pdf_match(ctx: Context, path_text: str, profiles: list[dict], drafts: list[dict]) -> dict:
    path = Path(path_text.strip().strip('"'))
    if not path.is_absolute() or not path.is_file():
        raise ApiError(f"PDF introuvable : {path_text}")
    if path.suffix.lower() != ".pdf":
        raise ApiError(f"ce n'est pas un PDF : {path.name}")
    import pypdfium2 as pdfium  # noqa: PLC0415

    try:
        doc = pdfium.PdfDocument(str(path))
        pages = len(doc)
        doc.close()
    except pdfium.PdfiumError:
        raise ApiError(f"PDF illisible : {path.name}") from None
    sha = pdf_mod.sha256(path)
    return {"path": str(path), "name": path.name, "pages": pages, "sha256": sha,
            "profiles": [p for p in profiles if p.get("source_pdf_sha256") == sha],
            "drafts": [d for d in drafts if d.get("source_pdf_sha256") == sha]}


# --- routes -------------------------------------------------------------------------------

def _pick(request: Request, data: dict) -> Response:
    ctx = ctx_of(request)
    kind = data.get("kind")
    if kind not in PICK_TITLES:
        raise ApiError("type de sélection inconnu")
    initial = str(data.get("initial") or "")
    if initial and Path(initial).is_file():
        initial = str(Path(initial).parent)
    if not initial and kind == "pdf":
        initial = str(ctx.root / "diffuseurs")
    picker = ctx.extra.get("picker", native_pick)
    return JSONResponse({"path": picker(kind, initial)})


async def pick(request: Request) -> Response:
    data = await body(request)
    return await run_in_threadpool(_pick, request, data)


async def file_info(request: Request) -> Response:
    data = await body(request)
    return JSONResponse(master_info(str(data.get("path") or "")))


async def preview(request: Request) -> Response:
    data = await body(request)
    ctx = ctx_of(request)
    result = await run_in_threadpool(probe_preview, ctx, str(data.get("path") or ""), str(data.get("profile") or ""))
    result["assign"] = default_assign(ctx, str(data.get("profile")), len(result["tracks"]))
    return JSONResponse(result)


async def summary(request: Request) -> Response:
    return JSONResponse(profile_summary(ctx_of(request), request.path_params["name"]))


async def audio_map(request: Request) -> Response:
    data = await body(request)
    assign = data.get("assign") or {}
    if not isinstance(assign, dict):
        raise ApiError("attribution des pistes illisible")
    return JSONResponse(audio_map_for(ctx_of(request), str(data.get("profile") or ""), assign,
                                      int(data.get("tracks") or 0)))


async def match_pdf(request: Request) -> Response:
    from pad_guard.ui.api import list_drafts, list_profiles  # noqa: PLC0415

    data = await body(request)
    ctx = ctx_of(request)

    def work() -> dict:
        profiles = list_profiles(ctx)
        return pdf_match(ctx, str(data.get("path") or ""), profiles, list_drafts(ctx, profiles))

    return JSONResponse(await run_in_threadpool(work))


def routes() -> list:
    return [
        Route("/api/pick", pick, methods=["POST"]),
        Route("/api/file-info", file_info, methods=["POST"]),
        Route("/api/probe-preview", preview, methods=["POST"]),
        Route("/api/profiles/{name}/summary", summary),
        Route("/api/audio-map", audio_map, methods=["POST"]),
        Route("/api/pdf-match", match_pdf, methods=["POST"]),
    ]
