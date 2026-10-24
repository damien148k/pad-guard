"""Phase 4a acceptance on the video fixtures (docs/ROADMAP.md): effective profile in the analysis,
reports unchanged since Phase 3 apart from the new lines, draft profiles, scan and delivery."""

from __future__ import annotations

import difflib
import json
import re
from pathlib import Path

import pymupdf
import pytest
import yaml
from typer.testing import CliRunner

from pad_guard import workdir as wd
from pad_guard.cli import app
from pad_guard.profiles import resolve_profile

from conftest import PROFILES, ROOT, TEST_PROFILES

pytestmark = pytest.mark.fixtures

CLASSIC = TEST_PROFILES / "test_classic.yaml"
ARTE = PROFILES / "arte_hd_sdr.yaml"
GOLDEN = ROOT / "tests" / "golden" / "phase3"


def invoke(*args: str):
    return CliRunner().invoke(app, list(args))


@pytest.fixture(scope="module")
def analysed(fixtures_dir, tmp_path_factory):
    cache: dict[tuple, tuple[int, str, Path]] = {}

    def get(name: str, profile: Path = CLASSIC):
        key = (name, str(profile))
        if key not in cache:
            out = tmp_path_factory.mktemp(name.replace(".", "_"))
            # Without thumbnails: the reports are compared with the Phase 3 ones, made without them.
            result = invoke("analyze", str(fixtures_dir / name), "--profile", str(profile), "--out", str(out),
                            "--no-thumbnails")
            assert result.exception is None or isinstance(result.exception, SystemExit), result.output
            cache[key] = (result.exit_code, result.output, out)
        return cache[key]

    return get


def _json(out: Path, name: str) -> dict:
    return json.loads((out / name).read_text(encoding="utf-8"))


def _profile_variant(tmp_path: Path, base: Path, name: str, mutate) -> Path:
    raw = yaml.safe_load(base.read_text(encoding="utf-8"))
    mutate(raw)
    path = tmp_path / name
    path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


# --- reports unchanged since Phase 3 -------------------------------------------------------------

VOLATILE = ("| Chemin |", "| SHA-256 |", "| Taille |", "| Date d'analyse |", "| Commande |", "| Relance")
CHANGED = ("| Profil |", "- Préfiltre avant mesure des niveaux :", "| Balayage |",  # rewritten lines
           "| Document de référence |")
NORM_GAPS = "### Écarts entre le profil et les normes (information)"
ADDED = ("| Statut du profil |", "| Empreinte du profil effectif |", "| Cadence prise en charge par PAD Guard |",
         "| Décodeur disponible |", "| Format de pixel mesurable par PAD Guard |", "| Cadence fixe |",
         "| Format du timecode |")


def _lines(md: str) -> list[str]:
    lines = [line for line in md.splitlines() if not line.startswith(VOLATILE)]
    for title, next_level in (("### Livraison", "## "), (NORM_GAPS, "#")):  # new sections, up to the next one
        if title in lines:
            start = lines.index(title)
            end = next(i for i in range(start + 1, len(lines)) if lines[i].startswith(next_level))
            lines = lines[:start] + lines[end:]
    return lines


@pytest.mark.parametrize("name, profile", [
    ("ok_prores.mov", CLASSIC), ("ok_dnxhr.mxf", CLASSIC), ("bad_levels.mov", CLASSIC), ("bad_audio.mov", CLASSIC),
    ("bad_structure.mov", CLASSIC), ("arte_ok.mov", ARTE), ("arte_4tracks.mov", ARTE), ("arte_bad.mov", ARTE),
])
def test_phase3_reports_unchanged(analysed, name, profile) -> None:
    _, _, out = analysed(name, profile)
    meta = resolve_profile(profile).profile.meta
    golden = (GOLDEN / f"{Path(name).stem}.md").read_text(encoding="utf-8")
    golden = golden.replace(f"{meta.name} v1.0 (", f"{meta.name} v{meta.version} (")  # profile versions since
    old = _lines(golden)
    md = (out / wd.REPORT_MD).read_text(encoding="utf-8")
    new = _lines(md)
    diff = [d for d in difflib.ndiff(old, new) if d[:2] in ("- ", "+ ") and d[2:].strip()]  # blank lines: no effect
    unexpected = [d for d in diff if not d[2:].startswith(CHANGED + (ADDED if d[0] == "+" else ()))]
    assert unexpected == [], "\n".join(unexpected)
    assert "### Livraison" in md
    fingerprint = resolve_profile(profile).fingerprint
    assert f"| Empreinte du profil effectif | `{fingerprint}` |" in md


def test_effective_profile_written(analysed) -> None:
    _, _, out = analysed("arte_ok.mov", ARTE)
    text = (out / wd.EFFECTIVE_PROFILE).read_text(encoding="utf-8")
    assert text == resolve_profile(ARTE).dumps()  # sorted keys, no date: same bytes every time
    data = json.loads(text)
    assert data["status"] == "validated" and data["fingerprint_sha256"] == resolve_profile(ARTE).fingerprint
    probe = _json(out, wd.PROBE)
    assert probe["profile"]["effective_sha256"] == data["fingerprint_sha256"]
    assert probe["video"]["fps"] == "25/1" and probe["video"]["scan_flag"] == "progressive"


def test_rerun_keeps_the_effective_profile(analysed, tmp_path) -> None:
    import shutil

    _, _, out = analysed("arte_ok.mov", ARTE)
    work = tmp_path / "copie"
    shutil.copytree(out, work)
    (work / wd.PROFILE).write_text("pas un profil", encoding="utf-8")  # unused: the effective profile is
    result = invoke("rerun", str(work))
    assert result.exit_code == 0, result.output
    for name in (wd.EVENTS, wd.VERDICT, wd.EFFECTIVE_PROFILE):
        assert (work / name).read_bytes() == (out / name).read_bytes(), name


# --- draft profiles ------------------------------------------------------------------------------


def test_draft_profile_never_says_conforme(analysed, tmp_path) -> None:
    def draft(raw):
        raw["meta"]["status"] = "draft"
        del raw["meta"]["validated_by"], raw["meta"]["validated_at"]

    profile = _profile_variant(tmp_path, CLASSIC, "brouillon.yaml", draft)
    code, output, out = analysed("ok_prores.mov", profile)
    verdict = _json(out, wd.VERDICT)
    assert code == 0 and verdict["status"] == "CONFORME" and verdict["indicative"] is True  # rules unchanged
    md = (out / wd.REPORT_MD).read_text(encoding="utf-8")
    assert "PROFIL NON VALIDÉ — résultat indicatif" in md.split("## 1. En-tête")[0]
    assert "**INDICATIF : sans anomalie bloquante**" in md
    bare = re.compile(r"(?<!NON-)CONFORME")
    assert not bare.search(md)
    assert not bare.search(" ".join(output.split())) and "INDICATIF" in output
    with pymupdf.open(out / wd.REPORT_PDF) as doc:
        assert not bare.search("".join(page.get_text() for page in doc))


def test_draft_non_conforme_is_indicative(analysed, tmp_path) -> None:
    def draft(raw):
        raw["meta"]["status"] = "draft"

    profile = _profile_variant(tmp_path, CLASSIC, "brouillon_nc.yaml", draft)
    _, _, out = analysed("bad_levels.mov", profile)
    md = (out / wd.REPORT_MD).read_text(encoding="utf-8")
    assert "**INDICATIF : NON-CONFORME**" in md and not re.search(r"(?<!NON-)CONFORME", md)


# --- scan, frame rate, delivery -----------------------------------------------------------------


def test_interlaced_fixture_detected(analysed) -> None:
    _, _, out = analysed("interlaced_prores.mov")
    scan = _json(out, wd.MEASUREMENTS)["scan"]
    assert scan["flag"] == "interlaced" and scan["detected"] == "interlaced" and scan["agrees"] is True
    assert scan["combed_frames"] == scan["moving_frames"] > 200


@pytest.mark.parametrize("profile, severity, source", [
    (CLASSIC, "blocking", "profil de test (fixtures)"),
    (ARTE, "minor", "Arte V2-01-03 §3.2.2.1 : « Les livraisons en 1080i50 seront encore acceptées jusqu'au 31/12/2027 »"),
])
def test_interlaced_master_severity_from_profile(analysed, profile, severity, source) -> None:
    """Really interlaced pictures: scan_interlaced, severity of the profile (Arte: tolerated until 2027)."""
    _, _, out = analysed("interlaced_prores.mov", profile)
    events = _json(out, wd.EVENTS)["events"]
    scan = [(e["type"], e["severity"], e["severity_source"]) for e in events
            if e["type"].startswith("scan_") or e["title"] == "Balayage"]
    assert scan == [("scan_interlaced", severity, source)]
    row = next(line for line in (out / wd.REPORT_MD).read_text(encoding="utf-8").splitlines()
               if line.startswith("| Balayage |"))
    assert "détecté : entrelacé" in row and "drapeau : tb (entrelacé)" in row


def test_progressive_fixture_detected(analysed) -> None:
    _, _, out = analysed("ok_prores.mov")
    scan = _json(out, wd.MEASUREMENTS)["scan"]
    assert scan["flag"] == "progressive" and scan["detected"] == "progressive" and scan["combed_frames"] == 0
    first = json.loads((out / "measurements_video.jsonl").read_text(encoding="utf-8").splitlines()[300])
    assert 0.5 < first["comb"] < 0.9


def test_master_25p_against_50i_delivery(analysed, tmp_path) -> None:
    def delivery_50i(raw):
        raw["format"]["delivery"] = {"scan": "interlaced_tff", "fps": ["25/1"], "codec": "test"}

    profile = _profile_variant(tmp_path, ARTE, "arte_50i.yaml", delivery_50i)
    code, _, out = analysed("arte_ok.mov", profile)
    _, _, reference = analysed("arte_ok.mov", ARTE)
    events = _json(out, wd.EVENTS)["events"]
    assert [(e["type"], e["severity"], e["source"]) for e in events] == [
        ("delivery_conversion_required", "info", "delivery")]
    assert events[0]["detail"].startswith("Master 25p progressif (détecté sur les images) ; ARTE G.E.I.E. attend du 50i")
    assert "conversion requise" in events[0]["detail"]
    verdict, before = _json(out, wd.VERDICT), _json(reference, wd.VERDICT)
    assert code == 0 and (verdict["status"], verdict["score"]) == (before["status"], before["score"]) == ("CONFORME", 100.0)
    assert _json(reference, wd.EVENTS)["events"] == []  # Arte V2 accepts 25p: no conversion
    md = (out / wd.REPORT_MD).read_text(encoding="utf-8")
    assert "Conversion requise avant livraison : balayage progressif → entrelacé" in md


def test_client_values_differing_from_norms_are_information(analysed) -> None:
    _, _, out = analysed("arte_ok.mov", ARTE)
    md = (out / wd.REPORT_MD).read_text(encoding="utf-8")
    gaps = md[md.index(NORM_GAPS):md.index("### Méthodes et limites")]
    assert "- video.y_tolerance_high_pct : ARTE G.E.I.E. 103,0 ; EBU R 103 105,0" in gaps
    assert "- audio.loudness.long.integrated_tolerance_lu : ARTE G.E.I.E. 1,0 ; EBU R 128 0,2" in gaps
    assert _json(out, wd.VERDICT)["status"] == "CONFORME" and _json(out, wd.EVENTS)["events"] == []


def test_norm_only_value_capped_at_minor(fixtures_dir, tmp_path) -> None:
    """bad_levels with a profile that leaves the area threshold to EBU R 103: recommendations only."""
    import shutil

    (tmp_path / "profiles").mkdir()
    (tmp_path / "normes").mkdir()
    for name in ("ebu_r103", "lumiris_maison"):
        shutil.copyfile(ROOT / "normes" / f"{name}.yaml", tmp_path / "normes" / f"{name}.yaml")

    def area_from_norm(raw):
        raw["meta"]["extends"] = ["ebu_r103", "lumiris_maison"]
        del raw["video"]["max_out_of_range_area_pct"]

    profile = _profile_variant(tmp_path / "profiles", CLASSIC, "p.yaml", area_from_norm)
    out = tmp_path / "out"
    result = invoke("analyze", str(fixtures_dir / "bad_levels.mov"), "--profile", str(profile), "--out", str(out))
    events = _json(out, wd.EVENTS)["events"]
    assert [(e["type"], e["frame_start"], e["frame_end"], e["severity"]) for e in events] == [
        ("white_clip", 300, 324, "minor"), ("black_crush", 375, 399, "minor")]  # blocking and major in Phase 3
    assert all(e["severity_source"].startswith("NORME (ebu_r103) : valeur absente du document du client, "
                                                "gravité plafonnée à minor") for e in events)
    assert result.exit_code == 0 and _json(out, wd.VERDICT)["status"] == "CONFORME"
