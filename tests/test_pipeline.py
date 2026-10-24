"""Phase 3 acceptance (docs/ROADMAP.md): structure, rules, verdict and report on the fixtures."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import av
import numpy as np
import pymupdf
import pytest
from PIL import Image
from typer.testing import CliRunner

from pad_guard import workdir as wd
from pad_guard.cli import EXIT_NON_CONFORME, EXIT_USAGE, app
from pad_guard.decode.video import read_frames
from pad_guard.measure.models import Measurements
from pad_guard.measure.video import out_of_range_masks
from pad_guard.report.thumbnails import limits_from

from conftest import PROFILES, TEST_PROFILES

pytestmark = pytest.mark.fixtures

CLASSIC = TEST_PROFILES / "test_classic.yaml"
ARTE = PROFILES / "arte_hd_sdr.yaml"


def invoke(*args: str):
    return CliRunner().invoke(app, list(args))


@pytest.fixture(scope="module")
def analysed(fixtures_dir, tmp_path_factory):
    """Run ``analyze`` once per (fixture, profile, options): returns (exit code, output, directory)."""
    cache: dict[tuple, tuple[int, str, Path]] = {}

    def get(name: str, profile: Path = CLASSIC, *extra: str):
        key = (name, profile.name, extra)
        if key not in cache:
            out = tmp_path_factory.mktemp(name.replace(".", "_"))
            result = invoke("analyze", str(fixtures_dir / name), "--profile", str(profile), "--out", str(out), *extra)
            assert result.exception is None or isinstance(result.exception, SystemExit), result.output
            cache[key] = (result.exit_code, result.output, out)
        return cache[key]

    return get


def events(out: Path) -> list[dict]:
    return json.loads((out / wd.EVENTS).read_text(encoding="utf-8"))["events"]


def verdict(out: Path) -> dict:
    return json.loads((out / wd.VERDICT).read_text(encoding="utf-8"))


def types(out: Path) -> set[str]:
    return {e["type"] for e in events(out)}


# --- roadmap acceptance -----------------------------------------------------------------------


@pytest.mark.parametrize("name", ["ok_prores.mov", "ok_dnxhr.mxf"])
def test_ok_fixtures_conform(analysed, name) -> None:
    code, output, out = analysed(name)
    v = verdict(out)
    assert code == 0, output
    assert v["status"] == "CONFORME" and v["counts"]["blocking"] == v["counts"]["major"] == 0
    assert "CONFORME" in output


def test_bad_levels_exactly_two_events(analysed) -> None:
    code, _, out = analysed("bad_levels.mov")
    assert code == EXIT_NON_CONFORME and verdict(out)["status"] == "NON-CONFORME"
    found = [(e["type"], e["tc_start"], e["tc_end"], e["frame_start"], e["frame_end"]) for e in events(out)]
    assert found == [
        ("white_clip", "10:00:02:00", "10:00:02:24", 300, 324),
        ("black_crush", "10:00:05:00", "10:00:05:24", 375, 399),
    ]
    white = events(out)[0]
    assert white["worst_value"] == 975 and white["threshold"] == 967 and white["area_pct_max"] == 100.0


def test_bad_audio(analysed) -> None:
    code, _, out = analysed("bad_audio.mov")
    assert code == EXIT_NON_CONFORME
    assert {"audio_loudness", "audio_true_peak"} <= types(out)
    peak = next(e for e in events(out) if e["type"] == "audio_true_peak")
    assert peak["tc_start"] == "10:00:05:00" and peak["worst_value"] > -1.0  # the burst at t = 15 s


def test_bad_structure(analysed) -> None:
    code, _, out = analysed("bad_structure.mov")
    assert code == EXIT_NON_CONFORME
    assert {"structure_bars", "structure_timecode"} <= types(out)
    start = next(e for e in events(out) if e["title"].startswith("Début du programme"))
    assert start["value_text"] == "00:00:10:00"


def test_arte_ok(analysed) -> None:
    code, output, out = analysed("arte_ok.mov", ARTE)
    assert code == 0, output
    assert verdict(out)["status"] == "CONFORME" and events(out) == []
    structure = json.loads((out / wd.STRUCTURE).read_text(encoding="utf-8"))
    assert structure["letterbox"]["matched_format"] == "1.77"


def test_arte_bad(analysed) -> None:
    code, _, out = analysed("arte_bad.mov", ARTE)
    assert code == EXIT_NON_CONFORME
    assert {"structure_bars_present", "audio_silent_track", "audio_true_peak"} <= types(out)
    bars = next(e for e in events(out) if e["type"] == "structure_bars_present")
    assert (bars["tc_start"], bars["tc_end"], bars["severity"]) == ("10:00:00:00", "10:00:04:24", "blocking")
    silent = sorted(e["group"] for e in events(out) if e["type"] == "audio_silent_track")
    assert silent == ["piste 3 (VF)", "piste 4 (VF)"]
    assert {e["severity_source"] for e in events(out) if e["type"] == "audio_silent_track"} == {"Arte §3.2.2.1"}
    md = (out / wd.REPORT_MD).read_text(encoding="utf-8")
    end = md.index("### Vignettes") if "### Vignettes" in md else md.index("## 7. Annexe")  # thumbnails by default
    later = md[md.index("### À vérifier"):end]
    assert "Mire présente" not in later  # blocking: main table only


def test_classic_structure_details(analysed) -> None:
    _, _, out = analysed("ok_prores.mov")
    s = json.loads((out / wd.STRUCTURE).read_text(encoding="utf-8"))
    assert [(b["frame_start"], b["frame_end"], b["pattern"]) for b in s["bars"]] == [(0, 124, "ebu_75")]
    assert [(t["frequency_hz"], t["level_dbfs"]) for t in s["tone"]] == [(1000.0, -18.0), (1000.0, -18.0)]
    assert s["head_black"] == {"frame_start": 125, "frame_end": 249}
    assert s["program"] == {"frame_start": 250, "frame_end": 499}
    assert s["findings"] == []


# --- report -----------------------------------------------------------------------------------


def test_pdf_is_french_and_fits_the_page(analysed) -> None:
    _, _, out = analysed("bad_levels.mov")
    md = (out / wd.REPORT_MD).read_text(encoding="utf-8")
    for section in ("## 1. En-tête", "## 2. Statut", "## 3. Synthèse", "## 4. Contrôles de format et de structure",
                    "## 5. Audio", "## 6. Anomalies (ordre chronologique)", "## 7. Annexe"):
        assert section in md
    assert "noyau [1 2 1]/4" in md  # decision of 8 October 2026: the prefilter is stated
    main = md[md.index("### Bloquantes et majeures"):md.index("### À vérifier")]
    assert "| 1 | 10:00:02:00 |" in main and "| 2 | 10:00:05:00 |" in main
    assert "règle : profil de test (fixtures)" in main
    with pymupdf.open(out / wd.REPORT_PDF) as doc:
        text = "".join(page.get_text() for page in doc)
        assert "NON-CONFORME" in text and "Anomalies (ordre chronologique)" in text and "Gravité" in text
        for page in doc:
            for x0, _, x1, *_ in page.get_text("blocks"):
                assert x0 >= 0 and x1 <= page.rect.width - 20, f"texte hors page p.{page.number + 1}"
    assert (out / wd.CHARTS / "luminance.png").is_file() and (out / wd.CHARTS / "loudness.png").is_file()


def test_thumbnails_paint_measured_pixels(analysed, fixtures_dir) -> None:
    _, _, out = analysed("bad_levels.mov", CLASSIC, "--thumbnails")
    names = sorted(p.name for p in (out / wd.THUMBNAILS).iterdir())
    assert names == ["evenement_001.png", "evenement_002.png"]
    white = np.asarray(Image.open(out / wd.THUMBNAILS / "evenement_001.png"))
    assert white.shape == (360, 640 + 8 + 640, 3)
    assert (white[:, 648:] == (255, 32, 32)).all()  # every pixel of frame 300 is above 103 %
    md = (out / wd.REPORT_MD).read_text(encoding="utf-8")
    assert "![Anomalie 1](vignettes/evenement_001.png)" in md and "| voir 1 |" in md


def test_masks_match_measurements(analysed, fixtures_dir) -> None:
    _, _, out = analysed("bad_levels.mov")
    m = Measurements.model_validate_json((out / wd.MEASUREMENTS).read_text(encoding="utf-8"))
    lines = (out / m.video.file).read_text(encoding="utf-8").splitlines()
    limits = limits_from(m.video_settings)
    for frame in read_frames(fixtures_dir / "bad_levels.mov", [0, 260, 310]):
        rec = json.loads(lines[frame.index])
        masks = out_of_range_masks(frame, limits)
        n = frame.y.size
        assert round(100 * masks["y_above"].sum() / n, 4) == rec["y_above_pct"]
        assert round(100 * masks["y_below"].sum() / n, 4) == rec["y_below_pct"]
        assert round(100 * masks["rgb_out"].sum() / n, 4) == rec["rgb_out_pct"]


# --- rerun ------------------------------------------------------------------------------------


def _copy(out: Path, tmp_path: Path) -> Path:
    dst = tmp_path / "copie"
    shutil.copytree(out, dst)
    return dst


def test_rerun_reproduces_every_step(analysed, tmp_path) -> None:
    _, _, out = analysed("bad_levels.mov")
    work = _copy(out, tmp_path)
    for name in (wd.STRUCTURE, wd.EVENTS, wd.VERDICT):
        (work / name).unlink()
    result = invoke("rerun", str(work))
    assert result.exit_code == EXIT_NON_CONFORME, result.output
    for name in (wd.STRUCTURE, wd.EVENTS, wd.VERDICT, wd.MEASUREMENTS, wd.PROBE):
        assert (work / name).read_bytes() == (out / name).read_bytes(), name
    run = json.loads((work / wd.RUN).read_text(encoding="utf-8"))
    assert run["reruns"][-1]["from_step"] == "structure" and "rerun" in run["reruns"][-1]["command"]


def test_report_command_needs_only_json(analysed, tmp_path) -> None:
    _, _, out = analysed("ok_prores.mov")
    work = _copy(out, tmp_path)
    (work / wd.REPORT_PDF).unlink()
    (work / wd.REPORT_MD).unlink()
    result = invoke("report", str(work))
    assert result.exit_code == 0, result.output
    assert (work / wd.REPORT_PDF).is_file()
    assert "Relance (report)" in (work / wd.REPORT_MD).read_text(encoding="utf-8")


def test_rerun_with_other_rules(analysed, tmp_path) -> None:
    _, _, out = analysed("bad_levels.mov")
    work = _copy(out, tmp_path)
    lenient = tmp_path / "lenient.yaml"
    text = CLASSIC.read_text(encoding="utf-8")
    blocking = '      - {if: "worst_value > 1004 or area_pct_max > 5", then: blocking, source: "profil de test (fixtures)"}\n'
    assert blocking in text
    text = text.replace(blocking, "")
    text = text.replace("  max_major: 0 ", "  max_major: 5 ")
    lenient.write_text(text, encoding="utf-8")
    result = invoke("rerun", str(work), "--from", "rules", "--profile", str(lenient))
    assert result.exit_code == 0, result.output
    assert verdict(work)["status"] == "CONFORME" and [e["severity"] for e in events(work)] == ["major", "major"]
    assert all(e["severity_source"] == "profil de test (fixtures)" for e in events(work))
    assert (work / wd.PROFILE).read_text(encoding="utf-8") == text  # the profile now used is kept


def test_rerun_refuses_profile_that_changes_measurements(analysed, tmp_path) -> None:
    _, _, out = analysed("bad_levels.mov")
    work = _copy(out, tmp_path)
    strict = tmp_path / "strict.yaml"
    strict.write_text(CLASSIC.read_text(encoding="utf-8").replace("y_tolerance_high_pct: 103.0",
                                                                  "y_tolerance_high_pct: 101.0"), encoding="utf-8")
    result = invoke("rerun", str(work), "--profile", str(strict))
    assert result.exit_code == EXIT_USAGE
    message = " ".join(result.output.split())
    assert "relancer « analyze »" in message and "Y toléré" in message
    assert (work / wd.VERDICT).read_bytes() == (out / wd.VERDICT).read_bytes()


def test_rerun_interlaced_limitation(analysed, tmp_path) -> None:
    _, _, out = analysed("arte_ok.mov", ARTE)
    work = _copy(out, tmp_path)
    probe = json.loads((work / wd.PROBE).read_text(encoding="utf-8"))
    probe["video"]["field_order"] = "tb"
    (work / wd.PROBE).write_text(json.dumps(probe), encoding="utf-8")
    invoke("rerun", str(work))
    md = (work / wd.REPORT_MD).read_text(encoding="utf-8")
    assert "Fichier entrelacé (tb)" in md and "images entières" in md


def test_rerun_refuses_old_measurements(analysed, tmp_path) -> None:
    _, _, out = analysed("ok_prores.mov")
    work = _copy(out, tmp_path)
    data = json.loads((work / wd.MEASUREMENTS).read_text(encoding="utf-8"))
    data["schema_version"] = 1
    (work / wd.MEASUREMENTS).write_text(json.dumps(data), encoding="utf-8")
    result = invoke("rerun", str(work))
    assert result.exit_code == EXIT_USAGE
    assert "format 1" in " ".join(result.output.split())


def test_preflight_refuses_null_before_measuring(fixtures_dir, tmp_path) -> None:
    profile = tmp_path / "null.yaml"
    profile.write_text(ARTE.read_text(encoding="utf-8").replace("    tolerance: 12 ", "    tolerance: null "),
                       encoding="utf-8")
    result = invoke("analyze", str(fixtures_dir / "arte_ok.mov"), "--profile", str(profile), "--out",
                    str(tmp_path / "o"))
    assert result.exit_code == EXIT_USAGE
    assert "structure.bars.tolerance » vaut null" in " ".join(result.output.split())
    assert not (tmp_path / "o" / wd.PROBE).exists()


# --- integrity --------------------------------------------------------------------------------


def _corrupt(src: Path, dst: Path, frames: list[int]) -> None:
    shutil.copyfile(src, dst)
    with av.open(str(dst)) as c:
        stream = c.streams.video[0]
        packets = [(p.pos, p.size) for p in c.demux(stream) if p.size]
    with dst.open("r+b") as f:
        for k in frames:
            f.seek(packets[k][0])
            f.write(b"\0" * 16)  # destroys the ProRes frame header


def test_integrity_errors_deduplicated(fixtures_dir, tmp_path) -> None:
    src = tmp_path / "corrompu.mov"
    _corrupt(fixtures_dir / "ok_prores.mov", src, [300, 301, 420])
    out = tmp_path / "out"
    result = invoke("analyze", str(src), "--profile", str(CLASSIC), "--out", str(out))
    assert result.exit_code == EXIT_NON_CONFORME, result.output
    integrity = [e for e in events(out) if e["type"] == "integrity"]
    titles = [e["title"] for e in integrity]
    assert "Nombre d'images décodées" in titles
    decode = [e for e in integrity if e["title"].startswith("Erreur de décodage")]
    assert len(decode) == len({e["title"] for e in decode})  # one event per distinct error
    header = next(e for e in decode if "invalid frame header" in e["title"])
    assert header["occurrences"] >= 2  # the log line and the exception of a packet are merged
    assert all(e["severity"] == "blocking" for e in integrity)
    md = (out / wd.REPORT_MD).read_text(encoding="utf-8")
    table = md[md.index("### Erreurs de décodage (dédoublonnées)"):md.index("## 5. Audio")]
    assert table.count("prores: invalid frame header") == 1
