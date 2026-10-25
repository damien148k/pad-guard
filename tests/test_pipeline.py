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


def test_true_peaks_grouped_across_audio_merge_gap(analysed, tmp_path) -> None:
    """Peaks less than rules.audio_merge_gap_seconds (3 s) apart: one event with their number and
    the highest peak; a peak 4 s before them stays alone. The severity does not change."""
    _, _, out = analysed("bad_audio.mov")
    work = tmp_path / "w"
    shutil.copytree(out, work)
    path = work / "measurements_audio.jsonl"
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        if round(rec["t"], 1) in (11.0, 16.0, 17.0):  # the burst of the fixture is at 15 s, -0.5 dBTP
            rec["tp"] = [-0.8, -0.8]
        lines.append(json.dumps(rec, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = invoke("rerun", str(work), "--from", "rules", "--no-thumbnails")
    assert result.exception is None or isinstance(result.exception, SystemExit), result.output
    burst = next(e for e in events(out) if e["type"] == "audio_true_peak")
    peaks = [e for e in events(work) if e["type"] == "audio_true_peak"]
    assert [(e["tc_start"], e["occurrences"], e["worst_value"]) for e in peaks] == [
        ("10:00:01:00", 1, -0.8), ("10:00:05:00", 3, burst["worst_value"])]
    assert peaks[0]["value_text"] == "-0,8 dBTP"
    assert peaks[1]["value_text"] == f"{burst['value_text']} au maximum, 3 dépassements"
    assert {e["severity"] for e in peaks} == {burst["severity"]}


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


def _without_black_limits(tmp_path: Path, severity: bool = False) -> Path:
    """The Arte profile with no limit for the black of head and tail, and (``severity``) still with its
    chain structure_black_too_long, else without it."""
    lines = ARTE.read_text(encoding="utf-8").splitlines(keepends=True)
    kept, skip = [], False
    for line in lines:
        if line.lstrip().startswith(("head_max_seconds:", "tail_max_seconds:")):
            continue
        if not severity and line.strip() == "structure_black_too_long:":
            skip = True
            continue
        if skip and line.lstrip().startswith("- {"):
            continue
        skip = False
        kept.append(line)
    assert len(lines) - len(kept) == (2 if severity else 4)
    path = tmp_path / "sans_limite_de_noir.yaml"
    path.write_text("".join(kept), encoding="utf-8")
    return path


def test_black_limit_not_requested_by_the_client(fixtures_dir, tmp_path) -> None:
    """No limit for the black of head and tail (no client value, no reference, no house rule): the analysis
    runs, without the severity chain of structure_black_too_long; the black is measured and shown « non
    demandé par le client », never an anomaly, no invented value (decision of Damien, 25 October 2026)."""
    from pad_guard import audio_map, pipeline
    from pad_guard.profiles import resolve_profile

    profile = _without_black_limits(tmp_path)
    resolved = resolve_profile(profile).profile
    assert pipeline.preflight(resolved, audio_map.from_profile(resolved).groups) == []
    out = tmp_path / "out"
    result = invoke("analyze", str(fixtures_dir / "arte_bad.mov"), "--profile", str(profile), "--out", str(out),
                    "--no-thumbnails")
    assert result.exit_code == EXIT_NON_CONFORME, result.output  # the bars of the fixture, not the black
    checks = {c["id"]: c for c in json.loads((out / wd.STRUCTURE).read_text(encoding="utf-8"))["checks"]}
    for id_ in ("head_black", "tail_black"):
        assert checks[id_]["status"] == "not_requested" and checks[id_]["expected"] == "non demandé par le client"
    assert "structure_black_too_long" not in types(out)
    assert "| Noir et silence de tête | non demandé par le client |" in (out / wd.REPORT_MD).read_text(encoding="utf-8")


def test_black_limit_needs_its_severity_only_when_set(tmp_path) -> None:
    from pad_guard import audio_map, pipeline
    from pad_guard.profiles import resolve_profile
    from pad_guard.rules.engine import severity_types

    with_limit = resolve_profile(ARTE).profile
    groups = audio_map.from_profile(with_limit).groups
    assert "structure_black_too_long" in severity_types(with_limit, groups)
    no_limit = resolve_profile(_without_black_limits(tmp_path, severity=True)).profile
    assert "structure_black_too_long" not in severity_types(no_limit, groups)
    # A limit set without its severity chain is still refused before measuring.
    raw = with_limit.model_dump(mode="json", by_alias=True, exclude_none=True)
    del raw["rules"]["severity"]["structure_black_too_long"]
    from pad_guard.rules.profile import Profile

    missing = Profile.model_validate(raw)
    assert "le profil n'a pas de gravité pour « rules.severity.structure_black_too_long »" in \
        pipeline.preflight(missing, groups)


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
    probe["video"]["field_order"], probe["video"]["scan_flag"] = "tb", "interlaced"
    (work / wd.PROBE).write_text(json.dumps(probe), encoding="utf-8")
    invoke("rerun", str(work))
    md = (work / wd.REPORT_MD).read_text(encoding="utf-8")
    assert "Fichier entrelacé (tb)" in md and "images entières" in md
    # Progressive pictures under an interlaced flag: the label is wrong, not the master (rules/scan.py).
    events = json.loads((work / wd.EVENTS).read_text(encoding="utf-8"))["events"]
    assert [(e["type"], e["severity"], e["title"]) for e in events] == [
        ("scan_flag_mismatch", "major",
         "Drapeau de balayage incorrect (tb) sur un master progressif : corriger l'étiquette à l'export")]
    assert events[0]["severity_source"].startswith("Lumiris")
    row = next(line for line in md.splitlines() if line.startswith("| Balayage |"))
    assert "détecté : progressif" in row and "drapeau : tb (entrelacé)" in row and row.endswith("| ÉCHEC |")


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


# --- Phase 5: what the local interface reads ----------------------------------------------------


def test_progress_json_and_report_json(fixtures_dir, tmp_path) -> None:
    out = tmp_path / "work"
    progress = out / wd.PROGRESS
    result = invoke("analyze", str(fixtures_dir / "bad_levels.mov"), "--profile", str(CLASSIC), "--out", str(out),
                    "--progress-json", str(progress))
    assert result.exit_code == EXIT_NON_CONFORME, result.output
    lines = [json.loads(x) for x in progress.read_text(encoding="utf-8").splitlines()]
    stages = [x["stage"] for x in lines if x["stage"] != "log"]
    firsts = list(dict.fromkeys(stages))
    assert firsts == ["probe", "measure_video", "measure_audio", "structure", "rules", "report", "done"]
    frames = [x for x in lines if x["stage"] == "measure_video"]
    assert frames[-1]["done"] == frames[-1]["total"] > 0
    assert lines[-1]["status"] == "NON-CONFORME" and lines[-1]["msg"] == "NON-CONFORME"
    run = json.loads((out / wd.RUN).read_text(encoding="utf-8"))
    assert run["finished_at"] >= run["analyzed_at"]

    view = json.loads((out / wd.REPORT_JSON).read_text(encoding="utf-8"))
    ev = events(out)
    assert view["verdict"]["status"] == verdict(out)["status"] and view["verdict"]["label"] == "NON-CONFORME"
    assert [e["key"] for e in view["events"]] == [f"{e['type']}@{e['frame_start']}@{e['group'] or ''}" for e in ev]
    assert view["duplicate_keys"] == []
    thumbs = [e for e in view["events"] if e["thumbnail"]]
    assert thumbs and all((out / e["thumbnail"]).is_file() for e in thumbs)
    assert view["synthesis"]["by_ai"] is False and "gabarit" in view["synthesis"]["note"]
    assert view["timeline"]["ticks"][0]["pct"] == 0 and view["timeline"]["ticks"][-1]["pct"] == 100
    assert view["checks"] and all({"label", "expected", "actual", "status"} <= set(c) for c in view["checks"])


def test_probe_preview_skips_the_hash(fixtures_dir) -> None:
    from pad_guard.probe import probe_file
    from pad_guard.profiles import resolve_profile

    prof = resolve_profile(CLASSIC).profile
    preview = probe_file(fixtures_dir / "ok_prores.mov", prof, CLASSIC, hash_source=False)
    full = probe_file(fixtures_dir / "ok_prores.mov", prof, CLASSIC)
    assert preview.source.sha256 == "" and len(full.source.sha256) == 64
    assert preview.model_copy(update={"source": full.source}) == full
