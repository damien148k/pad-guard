"""A norm drafted from its PDF (draft-profile --kind norme, review-profile) and the references between
norms: a client refers to a national recommendation, which refers itself to EBU norms (decisions of
Damien, 25 October 2026). No Ollama: the model is a fake client."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

import pdf_fixture
from pad_guard.cli import app
from pad_guard.draft import DraftError, available_norms, make_draft, proposed_extends
from pad_guard.draft import review
from pad_guard.profiles import from_json, resolve_profile
from pad_guard.profiles.resolve import capped_norm_values, load_norm
from pad_guard.rules.profile import ProfileError

from conftest import ROOT, TEST_PROFILES
from test_draft import R128_QUOTE, TP_QUOTE, FakeClient, finding

TITLE = "CST-RT-099 — Recommandation de test"


@pytest.fixture(scope="module")
def doc_pdf(tmp_path_factory) -> Path:
    return pdf_fixture.make(tmp_path_factory.mktemp("pdf") / "cst_rt099.pdf")


@pytest.fixture
def lab(tmp_path) -> Path:
    """tmp/normes (the norms of the repository) and tmp/profiles."""
    shutil.copytree(ROOT / "normes", tmp_path / "normes", ignore=shutil.ignore_patterns("sources", "drafts"))
    (tmp_path / "profiles").mkdir()
    return tmp_path


def _norm_draft(doc_pdf: Path, lab: Path):
    client = FakeClient({1: [
        finding("audio.true_peak_max_dbtp", -1, 1, TP_QUOTE),
        finding("audio.loudness.long.integrated_lufs", None, 1, R128_QUOTE, source_type="client_refers_to_norm",
                norm="EBU R128"),
        finding("audio.sample_rate", 48000, 2, "Audio | 48 kHz, 24 bits"),
    ]})
    return make_draft(doc_pdf, "cst_rt099", client, lab / "normes" / "drafts", kind="norm", title=TITLE,
                      doc_version="V1.0, 2026", norms_dir=lab / "normes")


def test_norm_draft_needs_title_and_version(doc_pdf, lab) -> None:
    with pytest.raises(DraftError, match="titre et version"):
        make_draft(doc_pdf, "cst_rt099", FakeClient(), lab / "normes" / "drafts", kind="norm")
    result = CliRunner().invoke(app, ["draft-profile", str(doc_pdf), "--name", "cst_rt099", "--kind", "norme"])
    assert result.exit_code != 0 and "--title et --doc-version" in " ".join(result.output.split())


def test_norm_draft_is_never_inherited(doc_pdf, lab) -> None:
    x, files = _norm_draft(doc_pdf, lab)
    assert files["yaml"] == lab / "normes" / "drafts" / "cst_rt099.yaml"
    text = files["yaml"].read_text(encoding="utf-8")
    assert text.startswith("# BROUILLON de norme « cst_rt099 »")
    data = yaml.safe_load(text)
    assert data["meta"]["kind"] == "norm" and data["meta"]["document"] == {"title": TITLE, "version": "V1.0, 2026"}
    assert data["meta"]["extends"] == ["ebu_r128"]  # the norms it cites, nothing else; no value copied
    assert data["audio"] == {"sample_rate": 48000, "true_peak_max_dbtp": -1}
    assert "cst_rt099" not in available_norms(lab / "normes")  # normes/drafts/ is not normes/


def _review(draft_yaml: Path, answers: list[str], *extra: str):
    return CliRunner().invoke(app, ["review-profile", str(draft_yaml), *extra], input="\n".join(answers) + "\n")


def test_review_writes_the_norm(doc_pdf, lab) -> None:
    _, files = _norm_draft(doc_pdf, lab)
    assert _review(files["yaml"], [], "--base", str(TEST_PROFILES / "test_classic.yaml")).exit_code != 0
    # Fields: audio.sample_rate (accepted), audio.loudness.long.integrated_lufs (reference: left empty),
    # audio.true_peak_max_dbtp (corrected: a norm's value always cites its page, asked again without it).
    # Then the reference to EBU R 128, confirmed, cited in another version; proposed only when cited (n).
    answers = ["a", "v", "c", "-2", "", "", "1", TP_QUOTE, "", "o", "V4.0, 2020", "", "n", "Vincent"]
    result = _review(files["yaml"], answers)
    text = " ".join(result.output.split())
    assert result.exit_code == 0, result.output
    assert "la page et la citation exacte du document sont obligatoires" in text
    out = lab / "normes" / "cst_rt099.yaml"
    norm = load_norm(out)
    meta = norm.meta
    assert meta.extends == ["ebu_r128"] and meta.applies == "on_reference" and meta.validated_by == "Vincent"
    assert [(r.norm, r.cited_version) for r in meta.refers_to] == [("ebu_r128", "V4.0, 2020")]
    assert meta.refers_to[0].source.startswith("CST-RT-099 V1.0, 2026 p. 1 : « Les mesures de loudness")
    assert norm.raw["audio"] == {"sample_rate": 48000, "true_peak_max_dbtp": -2.0}
    sources = norm.raw["sources"]
    assert sources["audio.sample_rate"].startswith("CST-RT-099 V1.0, 2026 p. 2 : « Audio | 48 kHz")
    assert "corrigé à la relecture" in sources["audio.true_peak_max_dbtp"]
    assert "loudness" not in norm.raw["audio"]  # the value of R 128 is not copied
    assert not (lab / "normes" / ".relecture").exists()
    assert "cst_rt099" not in proposed_extends([], lab / "normes")
    assert proposed_extends(["cst_rt099"], lab / "normes")[-2:] == ["cst_rt099", "lumiris_maison"]


def test_refused_reference_is_not_extended(doc_pdf, lab) -> None:
    _, files = _norm_draft(doc_pdf, lab)
    result = _review(files["yaml"], ["a", "v", "a", "n", "", "o", "Vincent"])
    assert result.exit_code == 0, result.output
    meta = load_norm(lab / "normes" / "cst_rt099.yaml").meta
    assert meta.extends == [] and meta.refers_to == [] and meta.applies == "always"


# --- references between norms ------------------------------------------------------------------


CLIENT = "Annexe test p. 2 §I.A : « RT 099 - TV - Rec Tech PAD fichier Diffuseurs »"


def _national_norm(lab: Path) -> None:
    norm = {
        "meta": {"kind": "norm", "name": "cst_test", "applies": "on_reference",
                 "document": {"title": "CST-RT-TEST — Recommandation de test", "version": "V1"},
                 "extends": ["ebu_r103", "ebu_r128"],
                 "refers_to": [
                     {"norm": "ebu_r103", "cited_version": "v2.0 (juin 2016)",
                      "source": "CST-RT-TEST V1 p. 5 : « Conformément à la recommandation EBU R 103 (v2.0 juin 2016) »"},
                     {"norm": "ebu_r128", "source": "CST-RT-TEST V1 p. 8 : « l'algorithme décrit dans la R 128 »"}]},
        "audio": {"sample_rate": 48000, "bit_depth": 24},
        "sources": {"audio.sample_rate": "CST-RT-TEST V1 p. 10 : « 48 kHz »",
                    "audio.bit_depth": "CST-RT-TEST V1 p. 10 : « 24 bits »"},
    }
    (lab / "normes" / "cst_test.yaml").write_text(yaml.safe_dump(norm, allow_unicode=True), encoding="utf-8")


def _client(lab: Path, refs: list[dict]) -> Path:
    raw = yaml.safe_load((TEST_PROFILES / "test_classic.yaml").read_text(encoding="utf-8"))
    raw["meta"]["extends"] = ["ebu_r103", "ebu_r128", "cst_test", "lumiris_maison"]
    raw["meta"]["refers_to"] = refs
    for section, key in (("audio", "sample_rate"), ("audio", "bit_depth"), ("video", "rgb_max_pct")):
        raw[section].pop(key, None)
    raw["audio"]["loudness"]["long"].pop("integrated_lufs")
    raw["audio"]["loudness"]["long"].pop("integrated_tolerance_lu")
    raw["sources"] = {k: v for k, v in (raw.get("sources") or {}).items()
                      if not k.startswith(("audio.sample_rate", "audio.bit_depth", "video.rgb_max_pct",
                                           "audio.loudness.long.integrated"))}
    path = lab / "profiles" / "client.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def test_reference_goes_through_the_norms_it_refers_to(lab) -> None:
    _national_norm(lab)
    r = resolve_profile(_client(lab, [{"norm": "cst_test", "source": CLIENT,
                                      "except": ["audio.sample_rate", "audio.loudness.long.integrated_tolerance_lu"]}]))
    o = r.origins
    # The national norm's own value, and the values of the norms it refers to: the client's requirements.
    assert o["audio.bit_depth"].file == "normes/cst_test.yaml" and o["audio.bit_depth"].referred_by == CLIENT
    assert o["audio.bit_depth"].source.startswith(f"{CLIENT}, par renvoi à CST-RT-TEST (norme : CST-RT-TEST V1 p. 10")
    lufs = o["audio.loudness.long.integrated_lufs"]
    assert lufs.file == "normes/ebu_r128.yaml" and lufs.referred_by == CLIENT
    assert lufs.source.startswith(f"{CLIENT}, par renvoi à CST-RT-TEST, puis à EBU R 128 (CST-RT-TEST V1 p. 8) "
                                  "(norme : EBU R 128")
    assert o["video.rgb_max_pct"].source.startswith(
        f"{CLIENT}, par renvoi à CST-RT-TEST, puis à EBU R 103 (CST-RT-TEST V1 p. 5)")
    # The fields outside the reference (except), down the chain: recommendations, capped.
    capped = capped_norm_values(r)
    assert {"audio.sample_rate", "audio.loudness.long.integrated_tolerance_lu"} <= set(capped)
    assert not {"audio.bit_depth", "audio.loudness.long.integrated_lufs", "video.rgb_max_pct"} & set(capped)
    assert o["audio.true_peak_max_dbtp"].file == "profiles/client.yaml"  # the client's value wins
    # The version cited is not the one of normes/: information for the report, kept by effective_profile.json.
    assert r.notes == ["CST-RT-TEST cite EBU R 103 v2.0 (juin 2016), version appliquée : version 3.0, mai 2020"]
    assert from_json(json.loads(r.dumps()), lab / "effective_profile.json").notes == r.notes


def test_direct_reference_wins_over_the_chain(lab) -> None:
    _national_norm(lab)
    direct = "Annexe test p. 7 : « conformes à la norme R128 »"
    r = resolve_profile(_client(lab, [{"norm": "cst_test", "source": CLIENT}, {"norm": "ebu_r128", "source": direct}]))
    lufs = r.origins["audio.loudness.long.integrated_lufs"]
    assert lufs.referred_by == direct and lufs.source.startswith(f"{direct}, par renvoi à EBU R 128 (norme")


def test_norm_reference_must_be_extended(lab) -> None:
    _national_norm(lab)
    path = lab / "normes" / "cst_test.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["meta"]["extends"] = ["ebu_r128"]
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ProfileError, match="ebu_r103 doit figurer dans extends"):
        load_norm(path)


def test_profiles_without_references_unchanged() -> None:
    """No note, no new key: effective_profile.json of Arte as before."""
    r = resolve_profile(ROOT / "profiles" / "arte_hd_sdr.yaml")
    assert r.notes == [] and "notes" not in json.loads(r.dumps())


def test_report_shows_the_cited_version(lab, tmp_path) -> None:
    from pad_guard.report import _Builder

    _national_norm(lab)
    r = resolve_profile(_client(lab, [{"norm": "cst_test", "source": CLIENT}]))
    work = tmp_path / "travail"
    work.mkdir()
    (work / "effective_profile.json").write_text(r.dumps(), encoding="utf-8")
    builder = object.__new__(_Builder)
    builder.dir = work
    assert builder.version_notes() == [
        "Version de norme : CST-RT-TEST cite EBU R 103 v2.0 (juin 2016), version appliquée : version 3.0, mai 2020."]


def test_review_load_of_a_norm_finds_its_norms(doc_pdf, lab) -> None:
    _, files = _norm_draft(doc_pdf, lab)
    rv = review.load(files["yaml"], None)
    assert rv.is_norm and rv.base is None and rv.norms == (lab / "normes").resolve()
    assert rv.doc == "CST-RT-099 V1.0, 2026"


# --- references the model missed -------------------------------------------------------------


def _pdf(path: Path, pages: list[list[str]]) -> Path:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(path), pagesize=A4)
    for lines in pages:
        y = 780
        for line in lines:
            c.drawString(60, y, line)
            y -= 20
        c.showPage()
    c.save()
    return path


R103_LIST = "EBU R 103 : Tolerances sur le signal video dans les systemes numeriques"
R103_REF = "Conformement a la recommandation EBU R 103 (v2.0 juin 2016), le gamut est surveille."
RATE = "Frequence d'echantillonnage : 48 kHz"


def test_alias_finds_the_reference_the_model_missed(lab, tmp_path) -> None:
    doc = _pdf(tmp_path / "rt_test.pdf", [["Documents de reference :", R103_LIST, "Signal video", R103_REF], [RATE]])
    client = FakeClient({1: [finding("audio.sample_rate", 48000, 2, RATE)]})  # the model sees no reference
    make_draft(doc, "cst_rt099", client, lab / "normes" / "drafts", kind="norm", title=TITLE,
               doc_version="V1.0, 2026", norms_dir=lab / "normes")
    draft_yaml = lab / "normes" / "drafts" / "cst_rt099.yaml"
    rv = review.load(draft_yaml, None)
    refs = review.reference_questions(rv)
    assert [(q.norm, q.found_by, q.candidates) for q in refs] == [("ebu_r103", "alias", [(1, R103_LIST), (1, R103_REF)])]
    # Manual references are checked in the PDF: a norm of normes/, the quote in its page, naming the norm.
    for name, page, quote, why in (("ebu_r999", "1", R103_REF, "n'est pas une norme de normes/"),
                                   ("lumiris_maison", "1", R103_REF, "n'est pas une norme de normes/"),
                                   ("ebu_r103", "2", R103_REF, "citation introuvable p. 2"),
                                   ("ebu_r128", "1", R103_REF, "ne nomme pas ebu_r128")):
        with pytest.raises(review.ReviewError, match=why):
            review.manual_reference(rv, name, page, quote)
    assert review.manual_reference(rv, "ebu_r103", "1", R103_REF).found_by == "manual"
    # The second line is the reference (the first one only lists the document), cited in another version;
    # then a manual reference refused (not in the page), and none more.
    answers = ["a", "2", "v2.0 (juin 2016)", "ebu_r128", "1", "conforme à la R128", "", "n", "Vincent"]
    result = _review(draft_yaml, answers)
    assert result.exit_code == 0, result.output
    text = " ".join(result.output.split())
    assert "EBU R 103 est nommée dans le document (alias du glossaire" in text and "citation introuvable p. 1" in text
    meta = load_norm(lab / "normes" / "cst_rt099.yaml").meta
    assert meta.extends == ["ebu_r103"]  # not proposed by the model, added because confirmed
    assert [(r.norm, r.cited_version) for r in meta.refers_to] == [("ebu_r103", "v2.0 (juin 2016)")]
    assert meta.refers_to[0].source == f"CST-RT-099 V1.0, 2026 p. 1 : « {R103_REF} »"


def test_alias_reference_adds_the_norm_to_the_profile(lab, tmp_path) -> None:
    """A broadcaster's annex refers to the RT 040 (meta.applies: on_reference, so not proposed): found by its
    alias, confirmed, it goes into extends before the house rules, and into refers_to."""
    _national_norm(lab)
    shutil.move(lab / "normes" / "cst_test.yaml", lab / "normes" / "cst_rt040.yaml")
    path = lab / "normes" / "cst_rt040.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace("name: cst_test", "name: cst_rt040"), encoding="utf-8")
    line = "Les normes sont decrites dans la RT 040 - TV - Rec Tech PAD fichier Diffuseurs V1.2-2016"
    doc = _pdf(tmp_path / "annexe.pdf", [[line], [RATE]])
    raw = yaml.safe_load((TEST_PROFILES / "test_classic.yaml").read_text(encoding="utf-8"))
    raw["meta"]["extends"] = ["ebu_r103", "ebu_r128", "lumiris_maison"]
    base = lab / "profiles" / "base.yaml"
    base.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    _, files = make_draft(doc, "annexe_test", FakeClient({1: [finding("audio.sample_rate", 48000, 2, RATE)]}),
                          lab / "profiles" / "drafts", broadcaster="Chaîne de test", norms_dir=lab / "normes",
                          profiles_dir=lab / "profiles")
    assert "cst_rt040" not in yaml.safe_load(files["yaml"].read_text(encoding="utf-8"))["meta"]["extends"]
    out = lab / "profiles" / "annexe_test.yaml"
    result = _review(files["yaml"], ["a", "o", "", "Vincent"], "--base", str(base), "--out", str(out))
    assert result.exit_code == 0, result.output
    r = resolve_profile(out)
    assert r.profile.meta.extends[-2:] == ["cst_rt040", "lumiris_maison"]
    assert [x.norm for x in r.profile.meta.refers_to] == ["cst_rt040"]
    assert r.profile.meta.refers_to[0].source == f"annexe.pdf p. 1 : « {line} »"


def test_citation_lines_without_symbol_bullets() -> None:
    assert review._clean("  ITU-R BT.709 :   Paramètres de codage vidéo HD") ==         "ITU-R BT.709 : Paramètres de codage vidéo HD"
