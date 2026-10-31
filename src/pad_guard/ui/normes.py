"""NORMES tab (``pad-guard ui --admin``): the norms of normes/ and the house values, their review table, the
signature.

Everything comes from PAD Guard's files and functions: the survey of releve-norme (``normes/releves/<name>.yaml``),
the norm (``normes/<name>.yaml``), the review table (``docs/normes/<name>.md``, ``docs/VALEURS_MAISON.md``) and
``draft.signature`` (the code of ``signer-norme``). The PDF of a norm is served from ``normes/sources/`` where it
lies, never copied. The page only shows and ticks; the server checks that every row was ticked before signing.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from pad_guard.draft import pdf as pdf_mod
from pad_guard.draft import releve, releve_edit, signature
from pad_guard.draft.schema import catalogue
from pad_guard.profiles.resolve import leaves, read_yaml
from pad_guard.rules.profile import ProfileError
from pad_guard.ui.analysis import jobs_of
from pad_guard.ui.api import model_flag
from pad_guard.ui.jobs import snapshot
from pad_guard.ui.server import ApiError, Context, body, ctx_of

NAME = re.compile(r"^[a-z0-9][a-z0-9_]{1,60}$")
HOUSE_LABEL = "Valeurs maison"
# Issuing body, read from the file name the repository gives every norm (ebu_, itu_, cst_).
BODIES = {"ebu": "UER (EBU)", "itu": "UIT-R", "cst": "CST", "smpte": "SMPTE", "lumiris": "Lumiris Production"}
# Unit of a field, from the suffix the profile schema gives its name.
UNITS = [("_lufs", "LUFS"), ("_lu", "LU"), ("_dbtp", "dBTP"), ("_dbfs", "dBFS"), ("_seconds", "s"), ("_pct", "%"),
         ("_frames", "images"), ("sample_rate", "Hz"), ("bit_depth", "bits"), ("_hz", "Hz")]
PDF_CSP = "default-src 'none'; object-src 'self'; frame-ancestors 'none'"


def _admin(request: Request) -> Context:
    ctx = ctx_of(request)
    if not ctx.admin:
        raise ApiError("onglet NORMES : lancer pad-guard ui --admin", 404)
    return ctx


def _name(name: str) -> str:
    if not NAME.match(name or ""):
        raise ApiError(f"nom de norme invalide : {name}")
    return name


def unit_of(path: str) -> str:
    leaf = path.rsplit(".", 1)[-1]
    return next((u for suffix, u in UNITS if leaf.endswith(suffix) or leaf.startswith(suffix)), "")


def _shown(value: Any) -> str:
    if isinstance(value, bool):
        return "oui" if value else "non"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _status(ctx: Context, name: str) -> dict:
    try:
        st = signature.status(name, ctx.root)
    except signature.SignatureError as exc:
        return {"state": "error", "label": "illisible", "problems": [str(exc)]}
    if not st.signed:
        return {"state": "to_review", "label": "à relire", "problems": []}
    when = st.at.strftime("%d/%m/%Y") if st.at else "?"
    if st.problems:
        return {"state": "modified", "label": "modifiée depuis la signature", "by": st.by, "at": when,
                "problems": st.problems}
    return {"state": "signed", "label": f"signée par {st.by} le {when}", "by": st.by, "at": when, "problems": []}


def _pdf(ctx: Context, shown: str | None) -> Path | None:
    """A PDF of normes/sources/, only there."""
    if not shown:
        return None
    sources = (ctx.root / "normes" / "sources").resolve()
    path = (ctx.root / shown).resolve()
    return path if path.is_relative_to(sources) and path.is_file() else None


def _survey(ctx: Context, name: str) -> releve.Survey | None:
    path = ctx.root / "normes" / "releves" / f"{name}.yaml"
    if not path.is_file():
        return None
    try:
        return releve.load(path)
    except releve.ReleveError as exc:
        raise ApiError(str(exc)) from None


def list_norms(ctx: Context) -> list[dict]:
    out = []
    for path in sorted((ctx.root / "normes").glob("*.yaml")):
        name = path.stem
        if name == "glossaire":
            continue
        try:
            meta = read_yaml(path).get("meta") or {}
        except ProfileError as exc:
            out.append({"name": name, "error": "; ".join(exc.messages)})
            continue
        if meta.get("kind") != "norm":
            continue
        doc = meta.get("document") or {}
        pdf = meta.get("source_pdf")
        out.append({"name": name, "title": HOUSE_LABEL if name == signature.HOUSE else doc.get("title"),
                    "document": doc.get("title"), "body": BODIES.get(name.split("_")[0]),
                    "version": doc.get("version"), "pdf": pdf,
                    "pdf_present": _pdf(ctx, pdf) is not None if pdf else None,
                    **{k: meta.get(k) for k in signature.INFO_KEYS},
                    "status": _status(ctx, name)})
    out.sort(key=lambda n: (n["name"] == signature.HOUSE, n["name"]))
    return out


def _house_rows(ctx: Context) -> list[dict]:
    """Rows of docs/VALEURS_MAISON.md, the table Vincent reads for lumiris_maison."""
    specs = {s.path: s.description for s in catalogue()}
    table = signature.table_path(signature.HOUSE, ctx.root)
    rows = []
    for line in table.read_text(encoding="utf-8").split("\n"):
        if not line.startswith("|"):
            continue
        cells = signature._cells(line)  # noqa: SLF001 - the parser of the table signature checks
        if len(cells) < 4 or not cells[0].isdigit():
            continue
        champ = cells[1].strip("`")
        rows.append({"key": f"m:{cells[0]}", "kind": "valeur", "champ": champ, "label": specs.get(champ, ""),
                     "valeur": cells[2], "unite": "", "page": None, "citation": cells[3], "quote": False,
                     "remarque": ""})
    return rows


def _survey_rows(ctx: Context, name: str, survey: releve.Survey) -> list[dict]:
    specs = {s.path: s.description for s in catalogue()}
    doc_key = lambda key: (f"/api/normes/{name}/pdf" + (f"?doc={key}" if key else ""))  # noqa: E731
    present = {None: _pdf(ctx, survey.meta.get("source_pdf")) is not None}
    present.update({k: _pdf(ctx, o.fichier) is not None for k, o in survey.autres_pdf.items()})
    label = {None: survey.libelle, **{k: o.libelle for k, o in survey.autres_pdf.items()}}
    rows = []
    for r in survey.meta.get("refers_to") or []:
        rows.append({"key": f"r:{r['norm']}", "kind": "renvoi", "champ": r["norm"], "label": "Renvoi à une norme",
                     "valeur": r.get("cited_version") or "", "unite": "", "page": None, "citation": r["source"],
                     "quote": False, "remarque": ""})
    for r in survey.valeurs:
        rows.append({"key": f"v:{r.champ}", "kind": "valeur", "champ": r.champ, "label": specs.get(r.champ, ""),
                     "valeur": _shown(r.valeur), "unite": unit_of(r.champ), "page": r.page, "document": label[r.pdf],
                     "pdf": doc_key(r.pdf) if present[r.pdf] else None, "citation": r.citation,
                     "quote": True, "remarque": r.remarque})
    for i, u in enumerate(survey.non_retenus):
        rows.append({"key": f"n:{i}", "kind": "non_retenu", "champ": u.sujet, "label": "Lu dans la norme, sans valeur",
                     "valeur": "", "unite": "", "page": u.page, "document": label[u.pdf],
                     "pdf": doc_key(u.pdf) if present[u.pdf] else None, "citation": u.citation,
                     "quote": True, "remarque": u.remarque})
    return rows


def _norm_rows(ctx: Context, name: str) -> list[dict]:
    """A norm without survey: its values and their « sources » lines."""
    data = read_yaml(ctx.root / "normes" / f"{name}.yaml")
    sources = data.pop("sources", {}) or {}
    meta = data.pop("meta", {}) or {}
    specs = {s.path: s.description for s in catalogue()}
    present = _pdf(ctx, meta.get("source_pdf")) is not None
    rows = []
    for path, value in leaves(data):
        src = str(sources.get(path, ""))
        page = re.search(r"\bp\. ?(\d+)", src)
        rows.append({"key": f"v:{path}", "kind": "valeur", "champ": path, "label": specs.get(path, ""),
                     "valeur": _shown(value), "unite": unit_of(path), "page": int(page.group(1)) if page else None,
                     "pdf": f"/api/normes/{name}/pdf" if present and page else None, "citation": src,
                     "quote": False, "remarque": ""})
    return rows


def rows_of(ctx: Context, name: str) -> list[dict]:
    if name == signature.HOUSE:
        return _house_rows(ctx)
    survey = _survey(ctx, name)
    return _survey_rows(ctx, name, survey) if survey else _norm_rows(ctx, name)


def correction_refusal(name: str, survey: releve.Survey | None) -> str | None:
    """Why the rows of this norm are not corrected from the page (None: « Corriger » by releve-norme)."""
    if name == signature.HOUSE:
        return "valeurs maison : correction dans normes/lumiris_maison.yaml et docs/VALEURS_MAISON.md"
    if survey is None:
        return f"pas de relevé (normes/releves/{name}.yaml) : correction à la main"
    if survey.fichier_norme == "verifier":
        return (f"norme héritée par des profils, dont Arte (fichier_norme: verifier) : correction à la main dans "
                f"normes/{name}.yaml, avec contrôle d'explain-profile Arte")
    return None


def sheet(ctx: Context, name: str) -> dict:
    item = next((n for n in list_norms(ctx) if n["name"] == name), None)
    if item is None:
        raise ApiError(f"norme introuvable : normes/{name}.yaml", 404)
    survey = _survey(ctx, name) if name != signature.HOUSE else None
    refusal = correction_refusal(name, survey)
    rows = rows_of(ctx, name)
    for r in rows:
        r["correctable"] = refusal is None and r["kind"] in ("valeur", "non_retenu")
    table = signature.table_path(name, ctx.root)
    return {**item, "rows": rows, "correction_refusal": refusal, "absents": survey.absents if survey else "",
            "table": str(table.relative_to(ctx.root)).replace("\\", "/"),
            "correction": ("normes/lumiris_maison.yaml et docs/VALEURS_MAISON.md" if name == signature.HOUSE
                           else f"pad-guard releve-norme normes/releves/{name}.yaml")}


async def get_norms(request: Request) -> Response:
    ctx = _admin(request)
    norms = await run_in_threadpool(list_norms, ctx)
    return JSONResponse({"norms": norms, "drafts": await run_in_threadpool(releve_edit.drafts, ctx.root)})


async def get_sheet(request: Request) -> Response:
    ctx = _admin(request)
    return JSONResponse(await run_in_threadpool(sheet, ctx, _name(request.path_params["name"])))


async def get_pdf(request: Request) -> Response:
    """The PDF where it lies in normes/sources/ (the page opens it at #page=N)."""
    ctx = _admin(request)
    name = _name(request.path_params["name"])
    survey = _survey(ctx, name)
    key = request.query_params.get("doc") or None
    if survey is not None:
        if key is not None and key not in survey.autres_pdf:
            raise ApiError(f"document inconnu : {key}", 404)
        shown = survey.autres_pdf[key].fichier if key else survey.meta.get("source_pdf")
    else:
        try:
            shown = (read_yaml(ctx.root / "normes" / f"{name}.yaml").get("meta") or {}).get("source_pdf")
        except ProfileError:
            shown = None
    path = _pdf(ctx, shown)
    if path is None:
        raise ApiError("PDF absent de normes/sources/ (non versionné, voir son README.md)", 404)
    return FileResponse(path, media_type="application/pdf", content_disposition_type="inline",
                        filename=path.name, headers={"content-security-policy": PDF_CSP})


async def sign(request: Request) -> Response:
    ctx = _admin(request)
    name = _name(request.path_params["name"])
    data = await body(request)
    by = " ".join(str(data.get("by") or "").split())
    if not by:
        raise ApiError("nom du validateur obligatoire")
    checked = set(data.get("checked") or [])
    keys = [r["key"] for r in await run_in_threadpool(rows_of, ctx, name)]
    missing = [k for k in keys if k not in checked]
    if missing:
        raise ApiError(f"signature refusée : {len(missing)} ligne(s) non cochée(s)")
    try:
        await run_in_threadpool(signature.sign, name, by, ctx.root)
    except signature.SignatureError as exc:
        raise ApiError(str(exc)) from None
    return JSONResponse(await run_in_threadpool(sheet, ctx, name))


async def correct(request: Request) -> Response:
    """« Corriger » : the row changed in the survey, checked by releve-norme in the PDF, norm and table rewritten."""
    ctx = _admin(request)
    name = _name(request.path_params["name"])
    data = await body(request)
    try:
        await run_in_threadpool(releve_edit.correct, name, str(data.get("key") or ""), data.get("valeur"),
                                data.get("page"), data.get("citation"), ctx.root)
    except (releve.ReleveError, pdf_mod.PdfError, ProfileError) as exc:
        message = "\n".join(exc.messages) if isinstance(exc, ProfileError) else str(exc)
        raise ApiError(message) from None
    return JSONResponse(await run_in_threadpool(sheet, ctx, name))


async def put_info(request: Request) -> Response:
    """Domain, region, replaced by: information in meta, no value changed, the signature stays."""
    ctx = _admin(request)
    name = _name(request.path_params["name"])
    data = await body(request)
    try:
        await run_in_threadpool(releve_edit.set_info, name, data, ctx.root)
    except releve.ReleveError as exc:
        raise ApiError(str(exc)) from None
    return JSONResponse(await run_in_threadpool(sheet, ctx, name))


async def start_draft(request: Request) -> Response:
    """A norm's PDF stored in normes/sources/ (copied there once, from the path chosen on this machine), then
    draft-profile --kind norme as a job (local AI, the model chosen on the page)."""
    ctx = _admin(request)
    data = await body(request)
    name = _name(str(data.get("name") or "").strip())
    if (ctx.root / "normes" / f"{name}.yaml").exists() or (ctx.root / "normes" / "releves" / f"{name}.yaml").exists():
        raise ApiError(f"{name} existe déjà dans normes/ : choisir un autre nom")
    title = " ".join(str(data.get("title") or "").split())
    version = " ".join(str(data.get("version") or "").split())
    if not title or not version:
        raise ApiError("titre et version du document obligatoires (ex. « EBU R 128 s2 », « V1, 2021 »)")
    model = model_flag("--model", data)
    src = Path(str(data.get("pdf") or "").strip().strip('"'))
    if not src.is_absolute() or not src.is_file() or src.suffix.lower() != ".pdf":
        raise ApiError(f"PDF introuvable : {src}")
    sources = ctx.root / "normes" / "sources"
    pdf = src
    if not src.resolve().is_relative_to(sources.resolve()):
        pdf = sources / src.name
        if pdf.exists() and pdf_mod.sha256(pdf) != pdf_mod.sha256(src):
            raise ApiError(f"un autre document porte déjà ce nom dans normes/sources/ : {src.name}")
        if not pdf.exists():
            sources.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, pdf)
    out = ctx.root / "normes" / "drafts"
    args = ["draft-profile", str(pdf), "--kind", "norme", "--name", name, "--title", title, "--doc-version", version,
            "--out-dir", str(out), *model]
    job = jobs_of(ctx).start("draft_norm", f"Relevé IA {name} · {pdf.name}", args, out / f"{name}.progression.jsonl")
    return JSONResponse(snapshot(job))


async def draft_to_survey(request: Request) -> Response:
    """The AI's proposals become the survey and the sheet of the norm (rows refused by the checks left out)."""
    ctx = _admin(request)
    name = _name(request.path_params["name"])
    try:
        _, kept, dropped = await run_in_threadpool(releve_edit.survey_from_draft, name, ctx.root)
    except (releve.ReleveError, pdf_mod.PdfError, ProfileError) as exc:
        message = "\n".join(exc.messages) if isinstance(exc, ProfileError) else str(exc)
        raise ApiError(message) from None
    return JSONResponse({"kept": kept, "dropped": dropped, "sheet": await run_in_threadpool(sheet, ctx, name)})


def routes() -> list:
    return [
        Route("/api/jobs/draft-norm", start_draft, methods=["POST"]),
        Route("/api/normes/drafts/{name}/survey", draft_to_survey, methods=["POST"]),
        Route("/api/normes/{name}/correct", correct, methods=["POST"]),
        Route("/api/normes/{name}/info", put_info, methods=["PUT"]),
        Route("/api/normes", get_norms),
        Route("/api/normes/{name}", get_sheet),
        Route("/api/normes/{name}/pdf", get_pdf),
        Route("/api/normes/{name}/sign", sign, methods=["POST"]),
    ]
