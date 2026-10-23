"""Phase 4b: draft-profile, review-profile, compare-profiles (SPEC §13), with a fake LLM client.

Nothing here talks to Ollama: the model answers are scripted.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml
from pydantic import BaseModel
from typer.testing import CliRunner

import pdf_fixture
from pad_checker.cli import app
from pad_checker.draft import DraftError, make_draft, pdf, verify, vocabulary
from pad_checker.draft.extract import BAD_VALUE, CONFLICT, INVALID, OK, UNVERIFIABLE
from pad_checker.draft.schema import SECTIONS, catalogue, response_schema
from pad_checker.llm import LLMClient, LLMError, LLMRequest
from pad_checker.profiles import resolve_profile
from pad_checker.rules.profile import Profile

from conftest import ROOT, TEST_PROFILES

TP_QUOTE = "le niveau des crêtes, mesuré en True Peak, ne doit pas dépasser -1 dBTP."
LOUD_QUOTE = "la valeur cible du Loudness intégré est de -23 LUFS"


class FakeClient(LLMClient):
    """Answers each batch with the findings scripted for its first page."""

    model = "faux-modele"

    def __init__(self, by_page: dict[int, list[dict]] | None = None, raw: str | None = None,
                 error: LLMError | None = None):
        self.by_page = by_page or {}
        self.raw = raw
        self.error = error
        self.requests: list[LLMRequest] = []

    def generate(self, request: LLMRequest) -> str:
        self.requests.append(request)
        if self.error:
            raise self.error
        if self.raw is not None:
            return self.raw
        first = int(request.prompt.split("=== Page ")[1].split(" ")[0])
        return json.dumps({"findings": self.by_page.get(first, [])}, ensure_ascii=False)


def finding(field: str, value, page: int, quote: str, unit: str | None = None) -> dict:
    return {"field": field, "value": value, "page": page, "quote": quote, "unit": unit}


@pytest.fixture(scope="module")
def doc_pdf(tmp_path_factory) -> Path:
    return pdf_fixture.make(tmp_path_factory.mktemp("pdf") / "chaine_test.pdf")


def draft(doc_pdf: Path, out: Path, client: FakeClient, name: str = "chaine_test"):
    return make_draft(doc_pdf, name, client, out, broadcaster="Chaîne de test")


def statuses(x) -> dict[str, str]:
    return {r.path: r.status for r in x.fields}


# --- schema ------------------------------------------------------------------------------------


def _model_leaves(model: type[BaseModel], prefix: str) -> set[str]:
    from pad_checker.draft.schema import _sub_model

    out = set()
    for name, f in model.model_fields.items():
        sub = _sub_model(f.annotation)
        path = prefix + (f.alias or name)
        out |= _model_leaves(sub, path + ".") if sub else {path}
    return out


def test_schema_covers_every_field_of_the_model() -> None:
    expected = set().union(*(_model_leaves(_sub(s), s + ".") for s in SECTIONS))
    fields = catalogue()
    assert {f.path for f in fields} == expected
    assert set(response_schema(fields)["properties"]["findings"]["items"]["properties"]["field"]["enum"]) == expected
    assert all(f.description for f in fields)  # every field explains itself, in French
    assert set(vocabulary.KEYWORDS) | vocabulary.INTERNAL == expected  # every field has its vocabulary


def _sub(section: str) -> type[BaseModel]:
    from pad_checker.draft.schema import _sub_model

    return _sub_model(Profile.model_fields[section].annotation)


# --- extraction --------------------------------------------------------------------------------


def test_correct_answer(doc_pdf, tmp_path) -> None:
    client = FakeClient({1: [finding("audio.true_peak_max_dbtp", "-1", 1, TP_QUOTE, "dBTP"),
                             finding("audio.loudness.long.integrated_lufs", -23, 1, LOUD_QUOTE, "LUFS"),
                             finding("audio.alignment_tone.hz", 1000, 1, "Le signal d'alignement 1.000 Hz", "Hz")],
                         3: []})
    x, files = draft(doc_pdf, tmp_path, client)
    assert statuses(x) == {"audio.true_peak_max_dbtp": OK, "audio.loudness.long.integrated_lufs": OK,
                           "audio.alignment_tone.hz": OK}
    data = yaml.safe_load(files["yaml"].read_text(encoding="utf-8"))
    assert data["audio"]["true_peak_max_dbtp"] == -1.0  # converted to the field type
    assert data["meta"]["status"] == "draft" and data["meta"]["source_pdf_sha256"] == pdf.sha256(doc_pdf)
    assert data["meta"]["extends"][-1] == "lumiris_maison"
    text = files["yaml"].read_text(encoding="utf-8")
    assert "true_peak_max_dbtp: -1.0  # A VERIFIER (p. 1) « le niveau des crêtes" in text
    assert "  - format.pix_fmt" in text  # fields not found are listed at the top
    log = [json.loads(line) for line in files["log"].read_text(encoding="utf-8").splitlines()]
    assert [entry["pages"] for entry in log] == [[1, 2], [3]] and log[0]["model"] == "faux-modele"
    assert client.requests[0].system and "audio.true_peak_max_dbtp" in client.requests[0].prompt
    assert len(client.requests[1].images) == 1  # page 3 has no text: rendered for the vision model


def test_invented_quote_is_refused(doc_pdf, tmp_path) -> None:
    x, files = draft(doc_pdf, tmp_path, FakeClient({1: [
        finding("audio.true_peak_max_dbtp", -1, 1, "Le true peak ne doit jamais dépasser -1 dBTP sur aucune piste.")]}))
    assert statuses(x) == {"audio.true_peak_max_dbtp": INVALID}
    data = yaml.safe_load(files["yaml"].read_text(encoding="utf-8"))
    assert data["audio"]["true_peak_max_dbtp"] is None
    assert "CITATION_INVALIDE" in files["yaml"].read_text(encoding="utf-8")


def test_number_missing_from_quote(doc_pdf, tmp_path) -> None:
    x, files = draft(doc_pdf, tmp_path, FakeClient({1: [finding("audio.true_peak_max_dbtp", -3, 1, TP_QUOTE)]}))
    [r] = x.fields
    assert r.status == INVALID and r.value is None and "nombre -3" in r.findings[0].reason
    assert yaml.safe_load(files["yaml"].read_text(encoding="utf-8"))["audio"]["true_peak_max_dbtp"] is None


def test_unrelated_quote_unit_and_programme_length(doc_pdf, tmp_path) -> None:
    x, _ = draft(doc_pdf, tmp_path, FakeClient({1: [
        finding("audio.silence_dbfs", -18, 1, "Le signal d'alignement 1.000 Hz est à -18 dBFS."),  # not silence
        finding("audio.loudness.long.integrated_tolerance_lu", 23, 1, "-23 LUFS avec une tolérance de ± 1 LU"),
        finding("audio.loudness.short.integrated_lufs", -23, 1, LOUD_QUOTE),  # the page speaks of long programmes
    ]}))
    reasons = {r.path: r.findings[0].reason for r in x.fields}
    assert all(r.status == INVALID for r in x.fields)
    assert "sans rapport" in reasons["audio.silence_dbfs"]
    assert "pas le nombre 23" in reasons["audio.loudness.long.integrated_tolerance_lu"]  # -23 is not 23
    assert "programmes longs" in reasons["audio.loudness.short.integrated_lufs"]


def test_two_values_make_a_conflict(doc_pdf, tmp_path) -> None:
    x, files = draft(doc_pdf, tmp_path, FakeClient({1: [
        finding("structure.timecode.program_start", "10:00:00:00", 2,
                "Le timecode de la première image du programme est 10:00:00:00."),
        finding("format.fps_allowed", ["25/1"], 2, "Fréquence image | 25 images par seconde"),
        finding("format.fps_allowed", ["50/1"], 1, "Consignes techniques de la chaîne de test, version 1."),
    ], 3: [finding("format.fps_allowed", ["24/1"], 3, "24 images par seconde")]}))
    s = statuses(x)
    assert s["structure.timecode.program_start"] == OK
    fps = next(r for r in x.fields if r.path == "format.fps_allowed")
    assert (fps.status, fps.value) == (OK, ["25/1"])  # 50/1: unrelated quote ; 24/1: page without text
    assert [f.status for f in fps.findings] == [OK, INVALID, UNVERIFIABLE]
    x, files = draft(doc_pdf, tmp_path, FakeClient({1: [
        finding("audio.true_peak_max_dbtp", -1, 1, TP_QUOTE),
        finding("audio.true_peak_max_dbtp", -1, 1, TP_QUOTE),  # same value twice: not a conflict
        finding("audio.loudness.long.integrated_lufs", -23, 1, LOUD_QUOTE),
        finding("audio.loudness.long.integrated_lufs", -18, 1, "Le signal d'alignement 1.000 Hz est à -18 dBFS."),
    ]}))
    assert statuses(x)["audio.true_peak_max_dbtp"] == OK
    assert statuses(x)["audio.loudness.long.integrated_lufs"] == OK  # -18: quote about the alignment tone


def test_conflict_kept_for_the_human(doc_pdf, tmp_path) -> None:
    x, files = draft(doc_pdf, tmp_path, FakeClient({1: [
        finding("audio.sample_rate", 48000, 2, "Audio | 48 kHz, 24 bits"),
        finding("audio.sample_rate", 48, 2, "Audio 48 kHz, 24 bits"),
    ]}))
    [r] = x.fields
    assert r.status == CONFLICT and r.value is None and len(r.findings) == 2
    text = files["yaml"].read_text(encoding="utf-8")
    assert "sample_rate: null  # CONFLIT : 48000" in text and "| 48 (p. 2" in text
    saved = json.loads(files["findings"].read_text(encoding="utf-8"))
    assert [f["value"] for f in saved["fields"][0]["findings"]] == [48000, 48]


def test_same_quote_same_value_two_fields_is_a_conflict(doc_pdf, tmp_path) -> None:
    quote = "Le signal d'alignement 1.000 Hz est à -18 dBFS."
    x, _ = draft(doc_pdf, tmp_path, FakeClient({1: [finding("audio.alignment_tone.dbfs", -18, 1, quote),
                                                    finding("structure.bars.tone_dbfs", -18, 1, quote)]}))
    assert set(statuses(x).values()) == {CONFLICT}


def test_page_without_text(doc_pdf, tmp_path) -> None:
    x, _ = draft(doc_pdf, tmp_path, FakeClient({3: [finding("structure.logo.forbidden", True, 3, "logo interdit")]}))
    assert statuses(x) == {"structure.logo.forbidden": UNVERIFIABLE}


def test_wrong_type_and_internal_parameters(doc_pdf, tmp_path) -> None:
    x, _ = draft(doc_pdf, tmp_path, FakeClient({1: [
        finding("audio.true_peak_max_dbtp", "beaucoup", 1, TP_QUOTE),
        finding("structure.black.y_max", 64, 1, TP_QUOTE),
    ]}))
    s = statuses(x)
    assert s["audio.true_peak_max_dbtp"] == BAD_VALUE and s["structure.black.y_max"] == INVALID


@pytest.mark.parametrize("client, message", [
    (FakeClient(raw="{\"findings\": [ {\"field\""), "mal formée"),
    (FakeClient(raw="{\"résultats\": []}"), "mal formée"),
    (FakeClient(error=LLMError("Ollama n'a pas répondu en 600 s (modèle faux-modele)")), "n'a pas répondu"),
])
def test_bad_answer_writes_nothing(doc_pdf, tmp_path, client, message) -> None:
    with pytest.raises(DraftError) as exc:
        draft(doc_pdf, tmp_path, client)
    assert message in str(exc.value) and "pages 1-2" in str(exc.value)
    assert list(tmp_path.iterdir()) == []


def test_quote_normalisation() -> None:
    page = "Le niveau ne doit pas dé-\npasser −1 dB TP en PCM. L’amorce est interdite."
    assert verify.quote_in("ne doit pas dépasser -1 dB TP", page)
    assert verify.quote_in("L'amorce est interdite", page)
    assert verify.value_in_quote(-1.0, "dépasser − 1 dB TP", r"db ?tp") is None
    assert verify.value_in_quote(-23.0, "- 23 LUFS", r"lufs") is None
    assert verify.value_in_quote(0.5, "tolérance de ± 0,5 LU", r"lu\b") is None
    assert verify.value_in_quote(120, "Programmes de durée supérieure à 2’00") is None
    assert verify.value_in_quote(1.0, "-1 dBTP") is not None  # the sign matters


# --- review-profile and compare-profiles -------------------------------------------------------


@pytest.fixture
def review_lab(doc_pdf, tmp_path):
    """tmp/profiles/chaine_test.yaml (copy of the test profile, extending the norms) + a draft."""
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    shutil.copytree(ROOT / "normes", tmp_path / "normes", ignore=shutil.ignore_patterns("sources"))
    raw = yaml.safe_load((TEST_PROFILES / "test_classic.yaml").read_text(encoding="utf-8"))
    raw["meta"]["extends"] = ["ebu_r103", "ebu_r128", "lumiris_maison"]
    base = profiles / "base.yaml"
    base.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    client = FakeClient({1: [
        finding("audio.true_peak_max_dbtp", -1, 1, TP_QUOTE),
        finding("audio.loudness.long.integrated_lufs", -23, 1, LOUD_QUOTE),
        finding("audio.sample_rate", 48000, 2, "Audio | 48 kHz, 24 bits"),
        finding("audio.sample_rate", 48, 2, "Audio 48 kHz, 24 bits"),
        finding("structure.timecode.program_start", "10:00:00:00", 2,
                "Le timecode de la première image du programme est 10:00:00:00."),
    ]})
    _, files = draft(doc_pdf, tmp_path / "drafts", client)
    return files["yaml"], base, profiles / "chaine_test.yaml"


def _review(draft_yaml: Path, base: Path, out: Path, answers: list[str]):
    return CliRunner().invoke(app, ["review-profile", str(draft_yaml), "--base", str(base), "--out", str(out)],
                              input="\n".join(answers) + "\n")


def test_review_profile_accept_correct_choose(review_lab) -> None:
    draft_yaml, base, out = review_lab
    # Field order: audio.sample_rate (conflict), audio.loudness.long.integrated_lufs, audio.true_peak_max_dbtp,
    # structure.timecode.program_start.
    result = _review(draft_yaml, base, out, ["1", "a", "c", "-3", "1", "le niveau des crêtes", "a", "Vincent"])
    assert result.exit_code == 0, result.output
    r = resolve_profile(out)
    assert r.profile.meta.status == "validated" and r.profile.meta.validated_by == "Vincent"
    assert r.profile.audio.sample_rate == 48000 and r.profile.audio.true_peak_max_dbtp == -3.0
    assert r.origins["audio.sample_rate"].source.startswith("chaine_test.pdf p. 2 : « Audio | 48 kHz")
    assert "corrigé à la relecture" in r.origins["audio.true_peak_max_dbtp"].source
    text = out.read_text(encoding="utf-8")
    assert "A VERIFIER : sans citation de chaine_test.pdf" in text  # base values not in the PDF
    assert draft_yaml.with_name("chaine_test.review.json").is_file()


def test_review_shows_norm_only_blocking_rules(review_lab) -> None:
    draft_yaml, base, out = review_lab
    # true peak left empty: inherited from EBU R 128 only, while audio_true_peak is blocking in the base.
    answers = ["1", "a", "v", "a"]
    result = _review(draft_yaml, base, out, answers + ["n"])
    text = " ".join(result.output.split())
    assert result.exit_code != 0 and not out.exists()
    assert "rules.severity.audio_true_peak (blocking) : audio.true_peak_max_dbtp" in text
    assert "plafonné à minor" in text
    result = _review(draft_yaml, base, out, answers + ["o", "Vincent"])
    assert result.exit_code == 0, result.output
    r = resolve_profile(out)
    assert r.origins["audio.true_peak_max_dbtp"].file == "normes/ebu_r128.yaml"


def test_review_refuses_incomplete_profile(review_lab, tmp_path) -> None:
    draft_yaml, base, out = review_lab
    raw = yaml.safe_load(base.read_text(encoding="utf-8"))
    del raw["structure"]["leaders"]
    base.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    result = _review(draft_yaml, base, out, ["1", "a", "a", "a"])
    assert result.exit_code != 0 and not out.exists()
    assert "structure.leaders" in " ".join(result.output.split())


def test_compare_profiles() -> None:
    result = CliRunner().invoke(app, ["compare-profiles", str(ROOT / "profiles" / "arte_hd_sdr.yaml"),
                                      str(ROOT / "profiles" / "france_tv_hd.yaml")], env={"COLUMNS": "250"})
    assert result.exit_code == 0, result.output
    text = " ".join(result.output.split())
    assert "audio.true_peak_max_dbtp" in text and "différent" in text and "structure.leaders" in text
