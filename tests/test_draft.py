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
from pad_guard.cli import app
from pad_guard.draft import DraftError, examples, glossary, make_draft, pdf, proposed_extends, verify, vocabulary
from pad_guard.draft.extract import (
    BAD_VALUE,
    CONFLICT,
    IMPLAUSIBLE,
    INVALID,
    NORM_REF,
    OK,
    UNVERIFIABLE,
    check,
)
from pad_guard.draft.schema import SECTIONS, catalogue, response_schema
from pad_guard.llm import LLMClient, LLMError, LLMRequest
from pad_guard.profiles import resolve_profile
from pad_guard.profiles.resolve import capped_norm_values
from pad_guard.rules.profile import Profile

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


def finding(field: str, value, page: int, quote: str, unit: str | None = None,
            source_type: str = "client_value", norm: str | None = None) -> dict:
    return {"field": field, "source_type": source_type, "value": value, "page": page, "quote": quote,
            "unit": unit, "norm": norm}


@pytest.fixture(scope="module")
def doc_pdf(tmp_path_factory) -> Path:
    return pdf_fixture.make(tmp_path_factory.mktemp("pdf") / "chaine_test.pdf")


def draft(doc_pdf: Path, out: Path, client: FakeClient, name: str = "chaine_test"):
    return make_draft(doc_pdf, name, client, out, broadcaster="Chaîne de test")


def statuses(x) -> dict[str, str]:
    return {r.path: r.status for r in x.fields}


# --- schema ------------------------------------------------------------------------------------


def _model_leaves(model: type[BaseModel], prefix: str) -> set[str]:
    from pad_guard.draft.schema import _sub_model

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
    item = response_schema(fields)["properties"]["findings"]["items"]
    assert item["properties"]["source_type"]["enum"] == ["client_value", "client_refers_to_norm", "not_found"]
    assert set(item["required"]) == {"field", "source_type", "value", "page", "quote", "unit", "norm"}


def test_glossary_covers_every_field_and_is_canonical() -> None:
    g = glossary.load()
    expected = {f.path for f in catalogue()} - vocabulary.INTERNAL
    assert set(g.champs) == expected
    assert all(t.fr and t.en for t in g.champs.values())
    assert glossary.dump(g) == glossary.GLOSSARY.read_text(encoding="utf-8")  # the tool rewrites it as is
    assert {"ebu_r128", "ebu_r103"} <= set(g.normes)
    assert "glossaire" not in proposed_extends()  # the glossary is not a norm


def _sub(section: str) -> type[BaseModel]:
    from pad_guard.draft.schema import _sub_model

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


# --- context size (num_ctx) ------------------------------------------------------------------


def test_context_is_computed_for_the_whole_run(doc_pdf, tmp_path) -> None:
    from pad_guard.draft.extract import ANSWER_TOKENS, estimate_tokens

    client = FakeClient()
    x, files = draft(doc_pdf, tmp_path, client)
    biggest = max(estimate_tokens(r.system, r.prompt, len(r.images)) for r in client.requests)
    assert client.num_ctx % 1024 == 0 and biggest + ANSWER_TOKENS <= client.num_ctx < biggest + ANSWER_TOKENS + 1024
    assert x.num_ctx == client.num_ctx
    log = [json.loads(line) for line in files["log"].read_text(encoding="utf-8").splitlines()]
    assert {entry["num_ctx"] for entry in log} == {client.num_ctx}  # one context for every batch
    assert f"contexte {client.num_ctx} jetons" in files["yaml"].read_text(encoding="utf-8")


def test_context_too_small_is_refused_before_any_request(doc_pdf, tmp_path) -> None:
    client = FakeClient()
    client.num_ctx = 4096  # the Ollama default
    with pytest.raises(DraftError) as exc:
        draft(doc_pdf, tmp_path, client)
    assert "contexte de 4096 jetons trop petit" in str(exc.value) and "--num-ctx" in str(exc.value)
    assert client.requests == [] and list(tmp_path.iterdir()) == []


class _FakeOllama:
    """Stands for ollama.Client: records the calls, answers as told."""

    calls: list[tuple[str, dict]] = []
    answer: object = None

    def __init__(self, host=None, timeout=None):
        pass

    def chat(self, **kwargs):
        _FakeOllama.calls.append(("chat", kwargs))
        if isinstance(_FakeOllama.answer, Exception):
            raise _FakeOllama.answer
        return _FakeOllama.answer

    def generate(self, **kwargs):
        _FakeOllama.calls.append(("generate", kwargs))


def _response(done_reason: str = "stop"):
    from ollama import ChatResponse, Message

    return ChatResponse(message=Message(role="assistant", content='{"findings": []}'), done_reason=done_reason,
                        prompt_eval_count=9195, eval_count=812)


def test_ollama_client_context_errors(monkeypatch) -> None:
    import ollama

    from pad_guard.llm import OllamaClient

    monkeypatch.setattr(ollama, "Client", _FakeOllama)
    _FakeOllama.calls = []
    request = LLMRequest(prompt="p", schema={"type": "object"})
    with pytest.raises(LLMError, match="num_ctx"):
        OllamaClient(model="m").generate(request)  # never sent without a context size
    client = OllamaClient(model="m", num_ctx=16384)
    _FakeOllama.answer = _response()
    assert client.generate(request) == '{"findings": []}'
    assert _FakeOllama.calls[-1][1]["options"] == {"temperature": 0, "seed": 1234, "num_ctx": 16384}
    assert (client.usage().prompt_tokens, client.usage().output_tokens) == (9195, 812)
    cases = [
        (ollama.ResponseError("request (9195 tokens) exceeds the available context size (4096 tokens), try "
                              "increasing it", 400), "demande de 9195 jetons, plus que le contexte de 4096"),
        (ollama.ResponseError("prediction aborted, token repeat limit reached", 500), "en boucle"),
        (_response("length"), "réponse coupée à la fin du contexte"),
    ]
    for answer, message in cases:
        _FakeOllama.answer = answer
        with pytest.raises(LLMError) as exc:
            client.generate(request)
        assert message in str(exc.value)
        if "jetons" in message:
            assert "--num-ctx 19456" in str(exc.value)  # 9195 + 10240 for the answer, rounded up
    client.release()
    assert _FakeOllama.calls[-1] == ("generate", {"model": "m", "prompt": "", "keep_alive": 0})


class _ReleasingClient(FakeClient):
    released = 0

    def release(self) -> None:
        _ReleasingClient.released += 1


@pytest.mark.parametrize("extra, code", [([], 0), (["--num-ctx", "4096"], 1)])
def test_cli_releases_the_model(doc_pdf, tmp_path, monkeypatch, extra, code) -> None:
    import pad_guard.cli as cli

    _ReleasingClient.released = 0
    monkeypatch.setattr(cli, "_ollama_or_exit", lambda model: _ReleasingClient())
    result = CliRunner().invoke(app, ["draft-profile", str(doc_pdf), "--name", "chaine_test",
                                      "--out-dir", str(tmp_path), *extra], env={"COLUMNS": "200"})
    assert result.exit_code == code, result.output
    assert _ReleasingClient.released == 1  # freed after success and after failure
    text = " ".join(result.output.split())
    assert ("Contexte :" in text) if code == 0 else ("trop petit" in text)


def test_quote_normalisation() -> None:
    page = "Le niveau ne doit pas dé-\npasser −1 dB TP en PCM. L’amorce est interdite."
    assert verify.quote_in("ne doit pas dépasser -1 dB TP", page)
    assert verify.quote_in("L'amorce est interdite", page)
    assert verify.value_in_quote(-1.0, "dépasser − 1 dB TP", r"db ?tp") is None
    assert verify.value_in_quote(-23.0, "- 23 LUFS", r"lufs") is None
    assert verify.value_in_quote(0.5, "tolérance de ± 0,5 LU", r"lu\b") is None
    assert verify.value_in_quote(120, "Programmes de durée supérieure à 2’00") is None
    assert verify.value_in_quote(1.0, "-1 dBTP") is not None  # the sign matters


def test_meaning_of_choices_and_prohibitions() -> None:
    quote = "Le programme ne doit pas contenir d’amorces de début et de fin ;"
    assert vocabulary.evidence("structure.leaders", '"none"', quote) is None
    assert "contredit" in vocabulary.evidence("structure.leaders", '"classic"', quote)
    assert vocabulary.evidence("structure.logo.forbidden", "true", "Aucun logo de chaîne dans le programme") is None
    assert vocabulary.evidence("structure.logo.forbidden", "true", "Le logo est en haut à droite") is not None
    assert vocabulary.evidence("format.field_order", '"tt"', "Entrelacement: Entrelacé / Upper Field First") is None
    assert vocabulary.evidence("format.field_order", '"progressive"', "Entrelacement: Entrelacé") is not None
    assert vocabulary.evidence("format.field_order", '"tb"', "Entrelacement: Entrelacé / Upper Field First") is not None
    assert vocabulary.evidence("format.field_order", '"bb"', "Entrelacement: Entrelacé / Upper Field First") is not None


def test_units_of_list_values() -> None:
    assert verify.value_in_quote([24, 16], "24 ou 16 bits", vocabulary.unit_of("audio.bit_depth_allowed")) is None
    reason = verify.value_in_quote([24, 16], "4, 8 ou 16 pistes en 24 bits", vocabulary.unit_of("audio.bit_depth_allowed"))
    assert reason and "16" in reason  # 16 is a number of tracks here
    assert verify.value_in_quote(8, "jusqu'à 8 pistes", vocabulary.unit_of("audio.max_pairs")) is not None


def test_table_rows_and_columns() -> None:
    table = [["", "Programmes courts (< 2 minutes)", "Programmes longs (≥2 minutes)"],
             ["Mesure cible (Integrated Loudness)", "≤ -23 LUFS", "-23 LUFS (+/- 1 LU)"],
             ["Excursion dynamique (LRA)", "non mesuré", "≤ 20 LU (+5 LU)"]]
    found = verify.table_row("Mesure cible (Integrated Loudness) -23 LUFS (+/- 1 LU)", [table])
    assert found == (table, 1)  # one cell left out, the words still in order in one row
    assert verify.table_row("Excursion dynamique -23 LUFS", [table]) is None  # words of two rows
    assert verify.table_column_kind(1.0, table, 1) == "long"
    assert verify.table_column_kind(20.0, table, 2) == "long"


def test_lists_compared_as_sets(doc_pdf, tmp_path) -> None:
    from pad_guard.draft.extract import canonical

    assert canonical(["50/1", "25/1"]) == canonical(["25/1", "50/1"])
    quote = "Fréquence image | 25 images par seconde"
    x, _ = draft(doc_pdf, tmp_path, FakeClient({1: [finding("format.fps_allowed", ["25/1"], 2, quote),
                                                    finding("format.delivery.fps", ["25/1"], 2, quote)]}))
    assert set(statuses(x).values()) == {OK}  # same quote for two fields: fine when it is not a number


R128_QUOTE = "Les mesures de loudness sont conformes à la recommandation EBU R128."


def test_reference_to_a_norm_gives_no_value(doc_pdf, tmp_path) -> None:
    x, files = draft(doc_pdf, tmp_path, FakeClient({1: [
        # The model copies the R 128 value it knows: ignored, the client did not write it.
        finding("audio.loudness.long.integrated_lufs", -23, 1, R128_QUOTE, source_type="client_refers_to_norm",
                norm="EBU R128"),
        finding("audio.loudness.short.integrated_lufs", None, 1,
                "Le loudness des programmes courts respecte la recommandation CST-RT-017.",
                source_type="client_refers_to_norm", norm="CST-RT-017"),
        finding("audio.loudness.method", None, 1, "Consignes techniques de la chaîne de test, version 1.",
                source_type="client_refers_to_norm", norm="EBU R128"),  # names no norm
        finding("audio.loudness.long.lra_max_lu", None, 1, R128_QUOTE,  # says nothing of the LRA
                source_type="client_refers_to_norm", norm="EBU R128"),
        finding("audio.true_peak_max_dbtp", None, 1, TP_QUOTE,  # « True Peak » is no norm (no number)
                source_type="client_refers_to_norm", norm="True Peak"),
        finding("audio.silence_dbfs", None, 1, "rien", source_type="not_found"),  # dropped
    ]}))
    s = statuses(x)
    assert s == {"audio.loudness.method": INVALID, "audio.loudness.long.integrated_lufs": NORM_REF,
                 "audio.loudness.short.integrated_lufs": NORM_REF, "audio.true_peak_max_dbtp": INVALID,
                 "audio.loudness.long.lra_max_lu": INVALID}
    reasons = {r.path: r.findings[0].reason for r in x.fields}
    assert "sans rapport" in reasons["audio.loudness.long.lra_max_lu"]
    assert "ne nomme aucune norme" in reasons["audio.true_peak_max_dbtp"]
    ref = next(r for r in x.fields if r.path == "audio.loudness.long.integrated_lufs")
    assert ref.value is None and ref.findings[0].norm == "ebu_r128" and "ignorée" in ref.findings[0].reason
    data = yaml.safe_load(files["yaml"].read_text(encoding="utf-8"))
    assert "integrated_lufs" not in (data.get("audio", {}).get("loudness", {}).get("long") or {})
    assert data["meta"]["extends"] == ["ebu_r103", "ebu_r128", "lumiris_maison"]  # the cited norm after the others
    text = files["yaml"].read_text(encoding="utf-8")
    assert "EBU R 128 (normes/ebu_r128.yaml) : p. 1" in text
    assert "CST-RT-017 (absente de normes/" in text
    assert "audio.loudness.long.integrated_lufs -> ebu_r128 (p. 1)" in text
    saved = json.loads(files["findings"].read_text(encoding="utf-8"))
    assert [(n["norm"], n["available"]) for n in saved["cited_norms"]] == [("cst_rt017", False), ("ebu_r128", True)]


def test_implausible_value_or_unit_is_kept_and_flagged(doc_pdf, tmp_path) -> None:
    x, files = draft(doc_pdf, tmp_path, FakeClient({1: [
        finding("audio.sample_rate", 48, 2, "Audio | 48 kHz, 24 bits", "kHz"),  # 48 Hz: a reading error
        finding("audio.true_peak_max_dbtp", -1, 1, TP_QUOTE, "LUFS"),  # unit of another field
        finding("audio.loudness.long.integrated_lufs", -23, 1, LOUD_QUOTE, "LUFS"),
    ]}))
    s = statuses(x)
    assert s["audio.sample_rate"] == IMPLAUSIBLE and s["audio.true_peak_max_dbtp"] == IMPLAUSIBLE
    assert s["audio.loudness.long.integrated_lufs"] == OK
    rate = next(r for r in x.fields if r.path == "audio.sample_rate")
    assert rate.value == 48 and "hors de la plage vraisemblable" in rate.findings[0].reason
    tp = next(r for r in x.fields if r.path == "audio.true_peak_max_dbtp")
    assert "unité citée « LUFS » incompatible" in tp.findings[0].reason
    text = files["yaml"].read_text(encoding="utf-8")
    assert "sample_rate: 48  # INVRAISEMBLABLE (valeur 48 hors de la plage vraisemblable" in text


def test_kept_value_with_rejected_others_may_be_incomplete(doc_pdf, tmp_path) -> None:
    _, files = draft(doc_pdf, tmp_path, FakeClient({1: [
        finding("audio.true_peak_max_dbtp", -1, 1, TP_QUOTE, "dBTP"),
        finding("audio.true_peak_max_dbtp", -3, 1, "niveau true peak de -3 dBTP"),  # invented: refused
    ]}))
    text = files["yaml"].read_text(encoding="utf-8")
    assert "1 autre(s) proposition(s) rejetée(s) avec une autre valeur : valeur peut-être incomplète" in text


def test_glossary_checks() -> None:
    g = glossary.load()
    assert glossary.implausible(g, "structure.timecode.program_start", "10:00:00:00", None) is None
    assert "mal formé" in glossary.implausible(g, "structure.timecode.program_start", "10:00:61:00", None)
    assert glossary.implausible(g, "format.fps_allowed", ["25/1", "50/1"], "i/s") is None
    assert "hors de la plage" in glossary.implausible(g, "format.fps_allowed", ["250/1"], None)
    assert glossary.implausible(g, "audio.true_peak_max_dbtp", -1, "dBTP max") is None  # starts with dBTP
    assert glossary.implausible(g, "structure.bars.tone_tolerance_db", 1, "dBFS") is not None  # dB is not dBFS
    assert g.norms_in("conformément à la R 128 et à l'EBU R103") == ["ebu_r128", "ebu_r103"]
    assert g.norms_in("R1280") == []


def test_glossary_term_names_the_field_and_is_learnt(tmp_path) -> None:
    from pad_guard.draft.pdf import Document, Page
    from pad_guard.draft.schema import catalogue as fields

    copy = tmp_path / "glossaire.yaml"
    shutil.copy(glossary.GLOSSARY, copy)
    g = glossary.load(copy)
    doc = Document(path=tmp_path / "x.pdf", sha256="", pages=[Page(1, "Seuil de mutisme des pistes : -60 dBFS.")])
    specs = {s.path: s for s in fields()}
    raw = finding("audio.silence_dbfs", -60, 1, "Seuil de mutisme des pistes : -60 dBFS.", "dBFS")
    assert check(doc, raw, specs, 1, [1], g).status == INVALID  # « silence » is not in the quote
    assert glossary.add_term(g, "audio.silence_dbfs", "fr", "seuil de mutisme")
    assert not glossary.add_term(g, "audio.silence_dbfs", "fr", "Seuil  de MUTISME")  # already known
    g = glossary.load(copy)  # written to the file
    assert "seuil de mutisme" in g.champs["audio.silence_dbfs"].fr
    assert check(doc, raw, specs, 1, [1], g).status == OK


def test_prompt_shows_glossary_of_the_fields_on_the_pages(doc_pdf, tmp_path) -> None:
    client = FakeClient()
    draft(doc_pdf, tmp_path, client)
    first, last = client.requests[0].prompt, client.requests[1].prompt
    assert "Glossaire des champs" in first and "- audio.true_peak_max_dbtp : termes : true peak" in first
    assert "Glossaire des champs" not in last  # page 3 has no text
    assert "client_refers_to_norm" in client.requests[0].system


def _validated(path: Path, broadcaster: str, quote: str, sha: str = "0" * 64) -> None:
    path.write_text(yaml.safe_dump({
        "meta": {"name": path.stem, "broadcaster": broadcaster, "status": "validated", "source_pdf_sha256": sha},
        "audio": {"true_peak_max_dbtp": -2.0},
        "sources": {"audio.true_peak_max_dbtp": quote, "format.codecs": "Lumiris : master interne"},
    }, allow_unicode=True), encoding="utf-8")


def test_examples_never_come_from_the_same_broadcaster(doc_pdf, tmp_path) -> None:
    profiles = tmp_path / "profiles"
    profiles.mkdir()
    _validated(profiles / "chaine_test_uhd.yaml", "Chaîne de test", "Chaîne §1 : crête vraie -2 dBTP")
    _validated(profiles / "autre.yaml", "Autre diffuseur", "Autre §2 : true peak -2 dBTP")
    _validated(profiles / "meme_pdf.yaml", "Nom différent", "Même PDF §3 : -2 dBTP", sha=pdf.sha256(doc_pdf))
    client = FakeClient()
    make_draft(doc_pdf, "chaine_test", client, tmp_path / "out", broadcaster="Chaîne de test",
               profiles_dir=profiles)
    prompt = client.requests[0].prompt
    assert "chez Autre diffuseur, « Autre §2 : true peak -2 dBTP » a donné -2.0" in prompt
    assert "Chaîne §1" not in prompt and "Même PDF" not in prompt and "master interne" not in prompt
    # The validated profiles of the repository: Arte's examples are never shown for an Arte PDF.
    arte = examples.collect(ROOT / "profiles", examples.Target(name="arte_hd_sdr"))
    assert arte == {}
    other = examples.collect(ROOT / "profiles", examples.Target(name="france_tv_hd", broadcaster="France Télévisions"))
    assert other and all(e.profile == "arte_hd_sdr.yaml" for items in other.values() for e in items)


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
    # structure.timecode.program_start. After the correction, no term is added to the glossary ("").
    result = _review(draft_yaml, base, out, ["1", "a", "c", "-3", "1", "le niveau des crêtes", "", "a", "Vincent"])
    assert result.exit_code == 0, result.output
    r = resolve_profile(out)
    assert r.profile.meta.status == "validated" and r.profile.meta.validated_by == "Vincent"
    assert r.profile.audio.sample_rate == 48000 and r.profile.audio.true_peak_max_dbtp == -3.0
    assert r.origins["audio.sample_rate"].source.startswith("chaine_test.pdf p. 2 : « Audio | 48 kHz")
    assert "corrigé à la relecture" in r.origins["audio.true_peak_max_dbtp"].source
    text = out.read_text(encoding="utf-8")
    assert "A VERIFIER : sans citation de chaine_test.pdf" in text  # base values not in the PDF
    assert draft_yaml.with_name("chaine_test.review.json").is_file()


def test_review_flags_implausible_and_learns_terms(review_lab, tmp_path) -> None:
    draft_yaml, base, out = review_lab
    # sample_rate: CONFLIT between 48000 and the implausible 48. True peak corrected, with a new term.
    answers = ["1", "a", "c", "-3", "1", "le niveau des crêtes", "plafond numérique", "f", "a", "Vincent"]
    result = _review(draft_yaml, base, out, answers)
    assert result.exit_code == 0, result.output
    text = " ".join(result.output.split())
    assert "INVRAISEMBLABLE" in text and "hors de la plage vraisemblable" in text
    learnt = glossary.load(tmp_path / "normes" / "glossaire.yaml")
    assert "plafond numérique" in learnt.champs["audio.true_peak_max_dbtp"].fr
    assert "plafond numérique" not in glossary.load().champs["audio.true_peak_max_dbtp"].fr  # repository untouched


def test_review_confirms_references_to_norms(review_lab, doc_pdf) -> None:
    _, base, out = review_lab
    client = FakeClient({1: [finding("audio.loudness.long.integrated_lufs", None, 1, R128_QUOTE,
                                     source_type="client_refers_to_norm", norm="EBU R128")]})
    _, files = draft(doc_pdf, base.parent.parent / "drafts_ref", client)
    # The field is left empty: inherited from EBU R 128. Reference refused: audio_loudness (blocking) would
    # rest on a norm only, so the red warning comes, and the reviewer stops.
    result = _review(files["yaml"], base, out, ["v", "n", "n"])
    text = " ".join(result.output.split())
    assert result.exit_code != 0 and not out.exists()
    assert "Le document renvoie à EBU R 128 (p. 1)" in text
    assert "rules.severity.audio_loudness (blocking) : audio.loudness.long.integrated_lufs" in text
    # Reference confirmed: the R 128 value is the client's requirement, no warning, no cap.
    result = _review(files["yaml"], base, out, ["v", "o", "Vincent"])
    assert result.exit_code == 0, result.output
    assert "rules.severity.audio_loudness" not in " ".join(result.output.split())
    r = resolve_profile(out)
    assert [x.norm for x in r.profile.meta.refers_to] == ["ebu_r128"]
    o = r.origins["audio.loudness.long.integrated_lufs"]
    assert o.file == "normes/ebu_r128.yaml" and o.referred_by.startswith("chaine_test.pdf p. 1 : « Les mesures de loudness")
    assert ", par renvoi à EBU R 128" in o.source
    assert r.origins["audio.true_peak_max_dbtp"].file == "profiles/chaine_test.yaml"  # the client's -3 wins
    assert "audio.loudness.long.integrated_lufs" not in capped_norm_values(r)
    saved = json.loads(files["yaml"].with_name("chaine_test.review.json").read_text(encoding="utf-8"))
    assert [x["norm"] for x in saved["references"]] == ["ebu_r128"]


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


def test_review_completes_or_removes_partial_sections() -> None:
    from pad_guard.draft import review

    data = {"format": {"width": 1920, "delivery": {"codec": "XDCAM"}},
            "audio": {"loudness": {"short": {"short_term_max_lufs": -20.0}}},
            "sources": {"format.delivery.codec": "p. 8", "audio.loudness.short.short_term_max_lufs": "p. 7"}}
    comments: dict[str, str] = {}
    answers = iter(["interlaced_tff", '["25/1"]', ""])
    missing = ["format.delivery.scan", "format.delivery.fps", "audio.loudness.short.integrated_lufs",
               "audio.loudness.short.integrated_tolerance_lu"]
    review.complete(data, comments, missing, "doc.pdf", ask=lambda _: next(answers), say=lambda _: None)
    assert data["format"]["delivery"] == {"codec": "XDCAM", "scan": "interlaced_tff", "fps": ["25/1"]}
    assert "short" not in data["audio"]["loudness"]  # empty answer: the incomplete section is removed
    assert "audio.loudness.short.short_term_max_lufs" not in data["sources"]
    assert comments["format.delivery.scan"].startswith("A VERIFIER")


def test_compare_profiles() -> None:
    result = CliRunner().invoke(app, ["compare-profiles", str(ROOT / "profiles" / "arte_hd_sdr.yaml"),
                                      str(ROOT / "profiles" / "france_tv_hd.yaml")], env={"COLUMNS": "250"})
    assert result.exit_code == 0, result.output
    text = " ".join(result.output.split())
    assert "audio.true_peak_max_dbtp" in text and "différent" in text and "structure.leaders" in text
