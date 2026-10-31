"""NORMES tab, lot 2: « Corriger » a row (checked in the PDF by the code of releve-norme), a norm's PDF read by
the local AI then turned into a survey (no Ollama here: the job is replaced, the findings written by hand), the
domain / region / superseded_by information, which changes no value (Arte unchanged)."""

from __future__ import annotations

import json

import yaml

from pad_guard.draft import releve, releve_edit
from pad_guard.draft.extract import CONFLICT, OK
from pad_guard.profiles import resolve_profile
from pad_guard.ui import jobs as jobs_mod

import pdf_fixture
from conftest import ROOT
from test_draft import TP_QUOTE
from test_releve import doc_pdf, lab  # noqa: F401  (fixtures)
from test_ui_normes import admin, root  # noqa: F401  (fixtures)

SHORT_TP = "mesuré en True Peak, ne doit pas dépasser -1 dBTP."


def _keys(admin, name):
    return [r["key"] for r in admin.get(f"/api/normes/{name}").json()["rows"]]


def test_correct_a_row_through_releve_norme(admin, root) -> None:  # noqa: F811
    survey = root / "normes" / "releves" / "cst_rt099.yaml"
    assert admin.post("/api/normes/cst_rt099/sign", json={"by": "Vincent", "checked": _keys(admin, "cst_rt099")}).is_success
    before = survey.read_text(encoding="utf-8")
    key = "v:audio.true_peak_max_dbtp"
    # Refused: the quote is not on that page, or lacks the number; nothing is written.
    r = admin.post("/api/normes/cst_rt099/correct", json={"key": key, "valeur": "-1.0", "page": 2, "citation": TP_QUOTE})
    assert r.status_code == 400 and "correction refusée" in r.json()["error"] and "trouvée p. 1" in r.json()["error"]
    assert r.json()["error"].endswith(releve_edit.STRICTER)
    assert "la fiche d'une norme reprend le texte du pdf ; pour une exigence plus stricte, utiliser les valeurs maison" \
        in r.json()["error"].lower()
    r = admin.post("/api/normes/cst_rt099/correct", json={"key": key, "valeur": "-2", "page": 1, "citation": TP_QUOTE})
    assert r.status_code == 400 and "-2" in r.json()["error"]
    assert survey.read_text(encoding="utf-8") == before
    # Accepted: the survey row changed, the norm and its table written again, the signature erased.
    r = admin.post("/api/normes/cst_rt099/correct", json={"key": key, "valeur": "-1", "page": "1", "citation": SHORT_TP})
    assert r.status_code == 200, r.text
    sheet = r.json()
    assert sheet["status"]["state"] == "to_review"
    row = next(x for x in sheet["rows"] if x["key"] == key)
    assert row["citation"] == SHORT_TP and "Corrigé le" in row["remarque"]
    norm = yaml.safe_load((root / "normes" / "cst_rt099.yaml").read_text(encoding="utf-8"))
    assert norm["audio"]["true_peak_max_dbtp"] == -1 and SHORT_TP in norm["sources"]["audio.true_peak_max_dbtp"]
    assert norm["meta"]["validated_by"] is None
    assert SHORT_TP in (root / "docs" / "normes" / "cst_rt099.md").read_text(encoding="utf-8")
    assert releve.load(survey).valeurs[1].champ == "audio.sample_rate"  # the other rows untouched, in order


def test_no_correction_for_inherited_norms_nor_house_values(admin) -> None:
    sheet = admin.get("/api/normes/ebu_r128").json()
    assert "Arte" in sheet["correction_refusal"] and not any(r["correctable"] for r in sheet["rows"])
    r = admin.post("/api/normes/ebu_r128/correct", json={"key": "v:audio.true_peak_max_dbtp", "valeur": "-1",
                                                         "page": 4, "citation": "x"})
    assert r.status_code == 400 and "explain-profile Arte" in r.json()["error"]
    house = admin.get("/api/normes/lumiris_maison").json()
    assert "lumiris_maison.yaml" in house["correction_refusal"]
    assert admin.get("/api/normes/cst_rt099").json()["rows"][0]["correctable"] is False  # a reference: not here


def test_information_changes_no_value(admin, root) -> None:  # noqa: F811
    arte = ROOT / "profiles" / "arte_hd_sdr.yaml"
    before = resolve_profile(arte, root / "normes")
    assert admin.post("/api/normes/cst_rt099/sign", json={"by": "Vincent", "checked": _keys(admin, "cst_rt099")}).is_success
    info = {"domain": "audio", "region": " France ", "superseded_by": ""}
    for name in ("cst_rt099", "ebu_r128", "ebu_r103", "lumiris_maison"):
        r = admin.put(f"/api/normes/{name}/info", json=info)
        assert r.status_code == 200, r.text
        assert (r.json()["domain"], r.json()["region"], r.json()["superseded_by"]) == ("audio", "France", None)
    assert admin.get("/api/normes/cst_rt099").json()["status"]["state"] == "signed"  # information, not a value
    survey = yaml.safe_load((root / "normes" / "releves" / "cst_rt099.yaml").read_text(encoding="utf-8"))
    assert survey["meta"]["domain"] == "audio"
    assert "# Relevé" not in (root / "normes" / "ebu_r128.yaml").read_text(encoding="utf-8")[:0]  # file kept
    after = resolve_profile(arte, root / "normes")
    assert after.fingerprint == before.fingerprint and after.profile == before.profile
    assert "# A VERIFIER Vincent" in (root / "normes" / "lumiris_maison.yaml").read_text(encoding="utf-8")
    r = admin.put("/api/normes/cst_rt099/info", json={"domain": "x" * 200})
    assert r.status_code == 400


def test_new_norm_pdf_stored_in_sources_and_drafted(admin, root, tmp_path, monkeypatch) -> None:  # noqa: F811
    started = []
    jobs = admin.app.state.ctx.extra["jobs"]
    monkeypatch.setattr(jobs, "start", lambda kind, title, args, progress, *a, **k: started.append((kind, args))
                        or jobs_mod.Job(id="x", kind=kind, title=title, args=args, command="", progress_file=str(progress),
                                        log_dir=str(tmp_path)))
    doc = pdf_fixture.make(tmp_path / "Recommandation test.pdf")
    body = {"pdf": str(doc), "name": "cst_rt098", "title": "CST-RT-098 — Essai", "version": "V2",
            "model": "qwen3-vl:8b-instruct"}
    assert admin.post("/api/jobs/draft-norm", json={**body, "title": ""}).status_code == 400
    assert admin.post("/api/jobs/draft-norm", json={**body, "name": "cst_rt099"}).status_code == 400  # exists
    r = admin.post("/api/jobs/draft-norm", json=body)
    assert r.status_code == 200, r.text
    copy = root / "normes" / "sources" / "Recommandation test.pdf"
    assert copy.read_bytes() == doc.read_bytes()
    kind, args = started[-1]
    assert kind == "draft_norm" and args[:3] == ["draft-profile", str(copy), "--kind"]
    assert args[args.index("--title") + 1] == "CST-RT-098 — Essai" and args[-2:] == ["--model", "qwen3-vl:8b-instruct"]
    assert args[args.index("--out-dir") + 1] == str(root / "normes" / "drafts")


def _findings(root, source_pdf: str) -> None:
    drafts = root / "normes" / "drafts"
    drafts.mkdir(exist_ok=True)
    good = {"field": "audio.true_peak_max_dbtp", "value": -1.0, "page": 1, "quote": TP_QUOTE, "status": OK}
    data = {"meta": {"kind": "norm", "name": "cst_rt098", "document": {"title": "CST-RT-098 — Essai", "version": "V2"},
                     "source_pdf": source_pdf, "extends": ["ebu_r128"]},
            "model": "qwen3-vl:8b-instruct",
            "fields": [{"path": "audio.true_peak_max_dbtp", "status": OK, "findings": [good]},
                       # The model's page is wrong: draft-profile would not have said OK, the check refuses it anyway.
                       {"path": "audio.sample_rate", "status": OK,
                        "findings": [{"field": "audio.sample_rate", "value": 48000, "page": 1,
                                      "quote": "Audio | 48 kHz, 24 bits", "status": OK}]},
                       {"path": "structure.timecode.program_start", "status": CONFLICT, "findings": []}],
            "cited_norms": [{"norm": "ebu_r128", "title": "EBU R 128", "available": True}]}
    (drafts / "cst_rt098.findings.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_ai_draft_becomes_the_same_sheet(admin, root) -> None:  # noqa: F811
    _findings(root, "normes/sources/cst_rt099.pdf")
    drafts = admin.get("/api/normes").json()["drafts"]
    assert [(d["name"], d["proposals"]) for d in drafts] == [("cst_rt098", 2)]
    r = admin.post("/api/normes/drafts/cst_rt098/survey")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["kept"] == 1 and len(out["dropped"]) == 2
    assert any(d.startswith("audio.sample_rate : ") and "p. 2" in d for d in out["dropped"])
    sheet = out["sheet"]
    assert sheet["status"]["state"] == "to_review" and [r["champ"] for r in sheet["rows"]] == ["audio.true_peak_max_dbtp"]
    assert sheet["rows"][0]["correctable"] and "qwen3-vl:8b-instruct" in sheet["rows"][0]["remarque"]
    assert "EBU R 128" in sheet["absents"]
    norm = yaml.safe_load((root / "normes" / "cst_rt098.yaml").read_text(encoding="utf-8"))
    assert norm["meta"]["extends"] == [] and norm["meta"]["applies"] == "on_reference"  # no reference taken alone
    assert admin.get("/api/normes").json()["drafts"] == []
    assert admin.post("/api/normes/drafts/cst_rt098/survey").status_code == 400  # never replaced
    # The same sheet: corrected and signed like any norm.
    keys = [r["key"] for r in sheet["rows"]]
    assert admin.post("/api/normes/cst_rt098/sign", json={"by": "Vincent", "checked": keys}).is_success


def test_item_replacement_keeps_comments() -> None:
    text = "meta:\n  name: x\n\nvaleurs:\n  # --- A ---\n  - champ: a\n    valeur: 1\n\n  # --- B ---\n  - champ: b\n    valeur: 2\n"
    out = releve_edit.replace_item(text, "valeurs", 0, {"champ": "a", "valeur": 3})
    assert out == text.replace("valeur: 1", "valeur: 3")
    out = releve_edit.replace_item(text, "valeurs", 1, {"champ": "b", "valeur": 4, "citation": "« x »"})
    assert out.endswith("  # --- B ---\n  - champ: b\n    valeur: 4\n    citation: « x »\n")
