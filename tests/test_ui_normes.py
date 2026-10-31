"""NORMES tab of the local interface (pad-guard ui --admin): list, review sheet, the PDF served where it lies,
the signature. No Ollama: the norm is a survey of a generated PDF (test_releve)."""

from __future__ import annotations

import shutil

import pytest
import yaml
from starlette.testclient import TestClient

from pad_guard.draft import releve
from pad_guard.ui import server

from conftest import ROOT
from test_releve import ROWS, _survey, doc_pdf, lab  # noqa: F401  (fixtures)

TOKEN = "jeton-de-test"


@pytest.fixture
def root(lab):  # noqa: F811
    """normes/ of the repository, plus cst_rt099 surveyed from a generated PDF, and the house table."""
    path = _survey(lab, ROWS, non_retenus=[{"sujet": "structure.timecode.program_start", "page": 2,
                                            "citation": "Le timecode de la première image du programme est 10:00:00:00",
                                            "remarque": "Exemple."}])
    releve.run(path, lab / "normes", lab / "docs" / "normes", root=lab)
    shutil.copy(ROOT / "docs" / "VALEURS_MAISON.md", lab / "docs" / "VALEURS_MAISON.md")
    (lab / "profiles").mkdir()
    return lab


def _client(root, tmp_path, admin: bool) -> TestClient:
    ctx = server.Context(token=TOKEN, hosts={"testserver"}, settings_file=tmp_path / "reglages.json", root=root,
                         admin=admin)
    return TestClient(server.create_app(ctx), headers={"X-PAD-Guard": TOKEN})


@pytest.fixture
def admin(root, tmp_path):
    with _client(root, tmp_path, True) as c:
        yield c


def test_tab_only_with_admin(root, tmp_path) -> None:
    with _client(root, tmp_path, False) as c:
        assert 'name="pad-guard-admin" content="0"' in c.get("/").text
        assert c.get("/api/normes").status_code == 404
        assert c.get("/api/normes/cst_rt099/pdf").status_code == 404
    with _client(root, tmp_path, True) as c:
        assert 'name="pad-guard-admin" content="1"' in c.get("/").text
        assert c.get("/api/normes").status_code == 200


def test_list_of_the_norms(admin) -> None:
    norms = {n["name"]: n for n in admin.get("/api/normes").json()["norms"]}
    assert "glossaire" not in norms and "ebu_r128" in norms
    n = norms["cst_rt099"]
    assert (n["body"], n["version"], n["pdf_present"]) == ("CST", "V1", True)
    assert n["status"] == {"state": "to_review", "label": "à relire", "problems": []}
    assert norms["ebu_r128"]["pdf_present"] is False  # normes/sources/ of the lab holds only the test PDF
    house = norms["lumiris_maison"]
    assert house["title"] == "Valeurs maison" and house["pdf"] is None
    assert list(norms)[-1] == "lumiris_maison"


def test_sheet_rows_and_the_pdf_at_its_page(admin, root) -> None:
    sheet = admin.get("/api/normes/cst_rt099").json()
    kinds = [r["kind"] for r in sheet["rows"]]
    assert kinds == ["renvoi", "valeur", "valeur", "non_retenu"]
    tp = next(r for r in sheet["rows"] if r["champ"] == "audio.true_peak_max_dbtp")
    assert (tp["valeur"], tp["unite"], tp["page"], tp["pdf"]) == ("-1.0", "dBTP", 1, "/api/normes/cst_rt099/pdf")
    assert tp["label"] and tp["quote"] is True
    assert sheet["rows"][0]["citation"].startswith("CST-RT-099 V1 p. 1")  # the reference, with its quote
    r = admin.get(tp["pdf"])
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].startswith("inline")
    assert r.content == (root / "normes" / "sources" / "cst_rt099.pdf").read_bytes()
    assert "object-src 'none'" not in r.headers["content-security-policy"]
    assert admin.get("/api/normes/cst_rt099/pdf?doc=..").status_code == 404
    assert admin.get("/api/normes/ebu_r128/pdf").status_code == 404  # PDF absent: a clear refusal
    assert admin.get("/api/normes/Mauvais..nom").status_code == 400


def test_house_values_sheet(admin) -> None:
    rows = admin.get("/api/normes/lumiris_maison").json()["rows"]
    assert len(rows) == 23 and rows[0]["champ"] == "format.unknown_color_tags_severity"
    assert rows[0]["valeur"] == "minor" and rows[0]["page"] is None and rows[0]["quote"] is False
    assert rows[-1]["champ"] == "rules.severity.blanking_inexact"  # décision Vincent, 31/10/2026


def test_sign_needs_every_row_then_a_change_shows(admin, root) -> None:
    keys = [r["key"] for r in admin.get("/api/normes/cst_rt099").json()["rows"]]
    r = admin.post("/api/normes/cst_rt099/sign", json={"by": "Vincent", "checked": keys[:-1]})
    assert r.status_code == 400 and "non cochée" in r.json()["error"]
    assert admin.post("/api/normes/cst_rt099/sign", json={"by": " ", "checked": keys}).status_code == 400
    r = admin.post("/api/normes/cst_rt099/sign", json={"by": "Vincent", "checked": keys})
    assert r.status_code == 200 and r.json()["status"]["state"] == "signed"
    assert r.json()["status"]["label"].startswith("signée par Vincent le ")
    norm = root / "normes" / "cst_rt099.yaml"
    meta = yaml.safe_load(norm.read_text(encoding="utf-8"))["meta"]
    assert meta["validated_by"] == "Vincent" and len(meta["validated_norm_sha256"]) == 64
    norm.write_text(norm.read_text(encoding="utf-8").replace("sample_rate: 48000", "sample_rate: 44100"),
                    encoding="utf-8")
    st = next(n for n in admin.get("/api/normes").json()["norms"] if n["name"] == "cst_rt099")["status"]
    assert st["state"] == "modified" and st["label"] == "modifiée depuis la signature"
    # Signing again is refused: the table no longer matches the file.
    r = admin.post("/api/normes/cst_rt099/sign", json={"by": "Vincent", "checked": keys})
    assert r.status_code == 400 and "a changé" in r.json()["error"]


def test_house_values_signed(admin, root) -> None:
    keys = [r["key"] for r in admin.get("/api/normes/lumiris_maison").json()["rows"]]
    r = admin.post("/api/normes/lumiris_maison/sign", json={"by": "Vincent", "checked": keys})
    assert r.status_code == 200 and r.json()["status"]["state"] == "signed"
    text = (root / "normes" / "lumiris_maison.yaml").read_text(encoding="utf-8")
    assert "# A VERIFIER Vincent" in text and 'validated_by: "Vincent"' in text
