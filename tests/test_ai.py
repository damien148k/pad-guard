"""Phase 4c: synthesis and qualifications by the local model, with a fake LLMClient (no Ollama).

The model only writes text: the verdict, events and measurements never change, every number it
writes must be in its inputs, and the template synthesis comes back at the slightest doubt.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pad_guard import pipeline, workdir as wd
from pad_guard.cli import app
from pad_guard.llm import LLMClient, LLMError, LLMRequest
from pad_guard.report import ai

from conftest import TEST_PROFILES

CLASSIC = TEST_PROFILES / "test_classic.yaml"
TEMPLATE_NOTE = "*Synthèse générée par gabarit à partir des compteurs (couche IA désactivée).*"
_IDS = re.compile(r"\(numéros ([\d, ]+)\)")

GOOD_SYNTHESIS = ["Le fichier est NON-CONFORME au profil test_classic : les blancs de l'anomalie 1 bloquent la livraison.",
                  "Les noirs de l'anomalie 2 sont à corriger ensuite, à l'étalonnage."]


def asked_ids(request: LLMRequest) -> list[int]:
    return [int(n) for n in _IDS.search(request.prompt)[1].split(", ")]


class Fake(LLMClient):
    """Answers from ``qualify(request, ids)`` and ``synthesis(request)``; records every request."""

    def __init__(self, qualify=None, synthesis=None, model: str = "fake-vl:1b"):
        self.model = model
        self.requests: list[LLMRequest] = []
        self.released = False
        self.qualify = qualify or (lambda _r, ids: {"qualifications": [
            {"anomalies": ids, "qualification": "défaut à corriger", "justification": "Valeur au-delà du seuil."}]})
        self.synthesis = synthesis or (lambda _r: {"synthese": GOOD_SYNTHESIS})

    def generate(self, request: LLMRequest) -> str:
        self.requests.append(request)
        if request.prompt.startswith("Demande : qualification"):
            answer = self.qualify(request, asked_ids(request))
        else:
            answer = self.synthesis(request)
        return answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)

    def release(self) -> None:
        self.released = True


class Down(LLMClient):
    model = "fake-vl:1b"

    def __init__(self, message: str = "Ollama n'a pas répondu en 300 s (modèle fake-vl:1b)"):
        self.message = message
        self.calls = 0

    def generate(self, request: LLMRequest) -> str:
        self.calls += 1
        raise LLMError(self.message)


@pytest.fixture(scope="module")
def analysed(fixtures_dir, tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("bad_levels_ai")
    result = CliRunner().invoke(app, ["analyze", str(fixtures_dir / "bad_levels.mov"), "--profile", str(CLASSIC),
                                      "--out", str(out)])
    assert result.exit_code == 4, result.output  # NON-CONFORME
    return out


@pytest.fixture
def work(analysed, tmp_path) -> Path:
    dst = tmp_path / "work"
    shutil.copytree(analysed, dst)
    return dst


def report(work: Path, client: LLMClient | None, thumbnails: bool | None = None, refresh: bool = False):
    options = None if client is None else ai.Options(client=client, refresh=refresh)
    pipeline.rerun(work, "report", None, "pad-guard report (test)", thumbnails, None, options)
    return (work / wd.REPORT_MD).read_text(encoding="utf-8"), options


def without_reruns(md: str) -> list[str]:
    return [line for line in md.splitlines() if not line.startswith("| Relance")]


def section3(md: str) -> str:
    return md.split("## 3. Synthèse", 1)[1].split("## 4.", 1)[0]


def rows(md: str) -> dict[int, list[str]]:
    out = {}
    for line in md.splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) == 11 and cells[0].isdigit():
            out[int(cells[0])] = cells
    return out


FROZEN = (wd.EVENTS, wd.VERDICT, wd.MEASUREMENTS, wd.STRUCTURE, wd.PROBE)


# --- reports ------------------------------------------------------------------------------------


@pytest.mark.fixtures
def test_llm_none_report_unchanged(analysed, work) -> None:
    md, _ = report(work, None)
    assert without_reruns(md) == without_reruns((analysed / wd.REPORT_MD).read_text(encoding="utf-8"))
    assert TEMPLATE_NOTE in md and not (work / wd.LLM_SYNTHESIS).exists()
    result = CliRunner().invoke(app, ["report", str(work), "--llm", "none"])
    assert result.exit_code == 4, result.output
    assert without_reruns((work / wd.REPORT_MD).read_text(encoding="utf-8")) == without_reruns(md)


@pytest.mark.fixtures
def test_good_answer_inserted(analysed, work) -> None:
    fake = Fake()
    md, options = report(work, fake)
    s3 = section3(md)
    assert GOOD_SYNTHESIS[0] in s3 and GOOD_SYNTHESIS[1] in s3
    assert ("*Rédigée par IA locale (fake-vl:1b, prompt synthese_v1) à partir des anomalies ci-dessous ; à relire. "
            "Le verdict est calculé par des règles.*") in s3
    assert "Avertissement" not in s3 and "gabarit" not in s3
    table = rows(md)
    assert table[1][9] == "*défaut à corriger*" and table[2][9] == "*défaut à corriger*"
    assert "qualification suggérée par l'IA, à valider : *défaut à corriger* (Valeur au-delà du seuil.)" in md
    assert "rédigées par le modèle local fake-vl:1b" in md and "2 retenue(s), 0 laissée(s) vide(s) sur 2" in md
    assert "la couche IA est désactivée" not in md
    for name in FROZEN:  # the model never changes the analysis
        assert (work / name).read_bytes() == (analysed / name).read_bytes(), name
    # one request per event with a thumbnail (vision), then the synthesis
    assert [len(r.images) for r in fake.requests] == [1, 1, 0] and fake.released
    assert "measurements" not in fake.requests[-1].prompt and "y_p99" not in fake.requests[-1].prompt
    assert "commence exactement par : « Verdict : NON-CONFORME. »" in fake.requests[-1].prompt
    assert options.outcome.paragraphs == GOOD_SYNTHESIS and fake.num_ctx >= 4096
    log = json.loads((work / wd.LLM_SYNTHESIS).read_text(encoding="utf-8"))
    assert log["model"] == "fake-vl:1b" and log["prompt_version"] == "synthese_v1" and log["complete"]
    assert len(log["prompt_sha256"]) == len(log["inputs_sha256"]) == len(log["fingerprint"]) == 64
    assert json.loads(log["requests"][-1]["response"]) == {"synthese": GOOD_SYNTHESIS}
    assert set(log["inputs"]["images_sha256"]) == {"1", "2"}


@pytest.mark.fixtures
def test_families_without_thumbnails(work) -> None:
    fake = Fake()
    md, _ = report(work, fake, thumbnails=False)
    assert [len(r.images) for r in fake.requests] == [0, 0, 0]  # white_clip and black_crush: two families
    assert rows(md)[1][9] == "*défaut à corriger*"


@pytest.mark.fixtures
def test_invented_number_falls_back(work) -> None:
    fake = Fake(synthesis=lambda _r: {"synthese": [GOOD_SYNTHESIS[0], "Les noirs descendent à 37 sur 12 images."]})
    md, options = report(work, fake)
    s3 = section3(md)
    assert "Le fichier « bad_levels.mov » est NON-CONFORME" in s3  # template
    assert "> **Avertissement** : synthèse IA écartée, contrôle de la synthèse en échec : nombre 37 absent" in s3
    assert GOOD_SYNTHESIS[0] not in s3
    assert rows(md)[1][9] == "*défaut à corriger*"  # the qualifications stand on their own checks
    assert options.outcome.fallback.startswith("contrôle de la synthèse en échec")


@pytest.mark.fixtures
@pytest.mark.parametrize("paragraphs, why", [
    (["Le fichier est CONFORME au profil.", "Rien à signaler sur l'anomalie 1."], "NON-CONFORME n'est pas écrit"),
    (["Le fichier est NON-CONFORME.", "Les noirs restent conformes à la tolérance."], "le mot « conforme »"),
    (["Le fichier est NON-CONFORME.", "Voir l'anomalie 9 à 10:00:02:00."], "anomalie 9 inexistante"),
    (["Le fichier est NON-CONFORME.", "Voir l'image à 10:00:03:07."], "timecode 10:00:03:07 absent"),
    (["Le fichier est NON-CONFORME.", "L'événement gamut_clip est à revoir."], "« gamut_clip » inexistant"),
    (["Un seul paragraphe NON-CONFORME."], "mal formée"),
])
def test_contradicted_verdict_falls_back(work, paragraphs, why) -> None:
    md, _ = report(work, Fake(synthesis=lambda _r: {"synthese": paragraphs}))
    s3 = section3(md)
    assert "Le fichier « bad_levels.mov » est NON-CONFORME" in s3 and why in s3


@pytest.mark.fixtures
def test_draft_profile_needs_indicatif(work) -> None:
    verdict = json.loads((work / wd.VERDICT).read_text(encoding="utf-8"))
    verdict["indicative"] = True
    (work / wd.VERDICT).write_text(json.dumps(verdict, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md, _ = report(work, Fake())
    assert "profil non validé : la mention « résultat indicatif » manque" in section3(md)
    ok = ["Résultat indicatif : le fichier est NON-CONFORME, profil non validé.", "L'anomalie 1 bloque."]
    fake = Fake(synthesis=lambda r: {"synthese": ok})
    md, _ = report(work, fake, refresh=True)  # same inputs: without refresh, the first answers are replayed
    assert '"indicatif": true' in fake.requests[-1].prompt
    assert "« Résultat indicatif, profil non validé : NON-CONFORME. »" in fake.requests[-1].prompt
    assert ok[0] in section3(md) and "Avertissement" not in section3(md)


@pytest.mark.fixtures
@pytest.mark.parametrize("client", [
    Fake(qualify=lambda _r, _ids: "pas du JSON", synthesis=lambda _r: "{\"synthese\": "),
    Down(),
    Down("Ollama a refusé la requête (500) : model runner has unexpectedly stopped"),
    Down("demande de 40000 jetons, plus que le contexte de 32768 jetons : Ollama la refuse"),
])
def test_model_failure_still_writes_the_report(work, client) -> None:
    md, options = report(work, client)
    s3 = section3(md)
    assert "Le fichier « bad_levels.mov » est NON-CONFORME" in s3 and "> **Avertissement** : synthèse IA écartée" in s3
    assert rows(md)[1][9] == "" and rows(md)[2][9] == ""
    assert "qualification IA laissée vide" in md
    assert (work / wd.REPORT_PDF).is_file()
    if isinstance(client, Down):
        assert client.calls == 1  # the first failure stops the AI layer
        assert json.loads((work / wd.LLM_SYNTHESIS).read_text(encoding="utf-8"))["complete"] is False
        report(work, fresh := Fake())  # an interrupted run is never replayed
        assert fresh.requests
    else:
        assert len(client.requests) == 6  # each request asked again once, with the schema reminded
        assert "réponse du modèle mal formée" in s3


@pytest.mark.fixtures
def test_qualification_out_of_list_left_empty(work) -> None:
    def qualify(_r, ids):
        value = "défaut à corriger" if ids == [1] else "probablement voulu"
        return {"qualifications": [{"anomalies": ids, "qualification": value, "justification": "Voir l'image."}]}

    md, options = report(work, Fake(qualify=qualify))
    assert rows(md)[1][9] == "*défaut à corriger*" and rows(md)[2][9] == ""
    assert "qualification IA laissée vide : qualification hors liste (« probablement voulu »)" in md
    assert GOOD_SYNTHESIS[0] in section3(md)  # the rest is not failed
    assert "> **Avertissement** : 1 qualification(s) suggérée(s) sur 2 laissée(s) vide(s)" in section3(md)


@pytest.mark.fixtures
def test_unknown_event_and_contradiction(work) -> None:
    def qualify(_r, ids):
        return {"qualifications": [
            {"anomalies": ids + [99], "qualification": "défaut à corriger", "justification": "Hors tolérance."},
            {"anomalies": [2], "qualification": "faux positif probable", "justification": "Mire."}]}

    md, options = report(work, Fake(qualify=qualify))
    assert rows(md)[1][9] == "*défaut à corriger*"  # 99 ignored, 1 kept
    assert rows(md)[2][9] == "" and "qualifications contradictoires" in md  # 2 asked alone: two answers


@pytest.mark.fixtures
def test_answers_replayed_while_inputs_unchanged(work) -> None:
    md, _ = report(work, Fake())
    log = (work / wd.LLM_SYNTHESIS).read_bytes()
    again, options = report(work, Down())  # would fail if it were called
    assert without_reruns(again) == without_reruns(md) and options.outcome.reused
    assert (work / wd.LLM_SYNTHESIS).read_bytes() == log
    fresh = Fake()
    report(work, fresh, refresh=True)  # --llm-refresh
    assert len(fresh.requests) == 3
    other = Fake(model="other-vl:2b")
    report(work, other)  # another model: other inputs
    assert len(other.requests) == 3
    changed = Fake(model="other-vl:2b")
    report(work, changed, thumbnails=False)  # no thumbnails: other inputs
    assert len(changed.requests) == 3


# --- checks -------------------------------------------------------------------------------------


DATA = json.dumps({"verdict": {"statut": "NON-CONFORME", "score": "0", "anomalies_par_gravite": {"bloquant": 2}},
                   "events": [{"n": 1, "type": "audio_loudness", "tc_debut": "10:00:49:16", "valeur": "-26,3 LUFS",
                               "regle": "Arte §3.3.2.4", "nombre": 20, "image": "1920x1080",
                               "detail": "130958 images"}]}, ensure_ascii=False)


@pytest.mark.parametrize("text, problem", [
    ("Loudness à -26,3 LUFS, soit -26 LUFS arrondi, à 10:00:49:16 (Arte §3.3.2.4).", None),
    ("20 silences, deux bloquantes, vingt silences, 130 958 images, image 1920x1080.", None),
    ("Loudness à -26,4 LUFS.", "nombre 26,4"),
    ("Écart de 3,3 LU.", "nombre 3,3"),
    ("À 10:00:49:17.", "timecode 10:00:49:17"),
    ("Vers 10:00.", "« 10:00 »"),
    ("Voir l'anomalie 3.", "anomalie 3 inexistante"),
    ("Anomalies 1 à 4.", "anomalie 4 inexistante"),
    ("Le type audio_silence domine.", "« audio_silence » inexistant"),
    ("Trois bloquantes.", "« Trois »"),
    ("Vingt-deux silences.", "« Vingt-deux »"),
    ("Les durées respectent le seuil.", "une anomalie a toujours dépassé le seuil"),
    ("Le niveau reste dans la tolérance.", "une anomalie a toujours dépassé le seuil"),
])
def test_text_checks(text, problem) -> None:
    problems = ai.text_problems(text, ai.Allowed(DATA, {1, 2}))
    if problem is None:
        assert problems == []
    else:
        assert any(problem in p for p in problems), problems


@pytest.mark.parametrize("status, indicative, text, ok", [
    ("NON-CONFORME", False, "Le fichier est NON-CONFORME.", True),
    ("NON-CONFORME", False, "Le fichier est non conforme.", False),
    ("NON-CONFORME", False, "NON-CONFORME, mais le son est conforme.", False),
    ("NON-CONFORME", False, "NON-CONFORME (non-conformité du loudness).", True),
    ("CONFORME", False, "Le fichier est CONFORME.", True),
    ("CONFORME", False, "Le fichier est CONFORME, pas NON-CONFORME.", False),
    ("CONFORME", True, "Résultat indicatif : sans anomalie bloquante.", True),
    ("CONFORME", True, "Résultat indicatif : le fichier est conforme.", False),
    ("NON-CONFORME", True, "Le fichier est NON-CONFORME.", False),
    ("NON-CONFORME", True, "Résultat indicatif : NON-CONFORME.", True),
    ("NON-CONFORME", False, "Résultat indicatif : NON-CONFORME.", False),
])
def test_verdict_checks(status, indicative, text, ok) -> None:
    label = {"NON-CONFORME": "NON-CONFORME", "CONFORME": "CONFORME"}[status]
    verdict = {"statut": status, "indicatif": indicative, "affiche": label}
    assert (ai.verdict_problems(text, verdict) == []) is ok


def test_qualification_checks() -> None:
    allowed = ai.Allowed(DATA, {1, 2})
    kept, rejected = ai.check_qualifications([
        {"anomalies": [1], "qualification": "À vérifier à l’écoute.", "justification": "Mixage VF à -26,3 LUFS."},
        {"anomalies": [2], "qualification": "défaut à corriger", "justification": "Mesuré à 99 %."},
    ], (1, 2), allowed)
    assert kept == {1: ai.Qualification("à vérifier à l'écoute", "Mixage VF à -26,3 LUFS.")}
    assert rejected == {2: "justification écartée : nombre 99 absent des données"}
    kept, rejected = ai.check_qualifications([{"anomalies": [1], "qualification": "défaut à corriger"}], (1, 2), allowed)
    assert kept == {} and rejected == {1: "justification absente", 2: "non qualifiée par le modèle"}
