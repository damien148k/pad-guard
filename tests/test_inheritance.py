"""Phase 4a: norms, profile inheritance, effective profile (SPEC §12). No video fixture needed."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from pad_guard import pipeline
from pad_guard.cli import EXIT_USAGE, app
from pad_guard.measure.scan import detect
from pad_guard.probe.models import VideoInfo
from pad_guard.profiles import from_json, load_norm, resolve_profile
from pad_guard.profiles.resolve import REPO_NORMS, is_norm, leaves, read_yaml
from pad_guard.rules.profile import ProfileError, ScanDetection, null_fields

from conftest import PROFILES, ROOT, TEST_PROFILES

runner = CliRunner()

# Values added to the Arte profile by v3 (format of delivery, scan detection, loudness method);
# every other value of the effective profile must be the one of the v2 profile.
V3_ADDITIONS = {
    "audio.loudness.method",
    "format.delivery.scan", "format.delivery.fps", "format.delivery.codec",
    "rules.severity.delivery_conversion_required",
    "rules.severity.scan_flag_mismatch", "rules.severity.scan_interlaced",
    "video.scan_detection.comb_ratio_min", "video.scan_detection.motion_min",
    "video.scan_detection.interlaced_min_pct", "video.scan_detection.progressive_max_pct",
    "video.scan_detection.min_moving_frames",
}


def _values(path: Path) -> dict:
    return {p: v for p, v in leaves(resolve_profile(path).values) if not p.startswith("meta.")}


def test_arte_effective_profile_identical_to_v2() -> None:
    old = _values(TEST_PROFILES / "arte_hd_sdr_v1_flat.yaml")
    new = _values(PROFILES / "arte_hd_sdr.yaml")
    assert {p: v for p, v in new.items() if p not in V3_ADDITIONS} == old
    assert set(new) - set(old) == V3_ADDITIONS


def test_arte_inherits_and_conflicts() -> None:
    r = resolve_profile(PROFILES / "arte_hd_sdr.yaml")
    assert r.profile.meta.status == "validated" and r.profile.meta.validated_by == "Damien"
    assert [layer.file for layer in r.layers] == [
        "normes/ebu_r128.yaml", "normes/ebu_r103.yaml", "normes/lumiris_maison.yaml", "profiles/arte_hd_sdr.yaml"]
    # The client's document is authoritative: every value Arte states is in the Arte profile, cited.
    assert r.origins["audio.true_peak_max_dbtp"].file == "profiles/arte_hd_sdr.yaml"
    assert r.origins["audio.true_peak_max_dbtp"].source.startswith("Arte §3.3.2.1")
    assert r.origins["audio.true_peak_max_dbtp"].replaced == [{"file": "normes/ebu_r128.yaml", "value": -1.0}]
    assert r.origins["video.y_max_legal"].file == "profiles/arte_hd_sdr.yaml"
    from_norms = {p for p, o in r.origins.items() if o.file in ("normes/ebu_r128.yaml", "normes/ebu_r103.yaml")}
    assert from_norms == {"audio.loudness.method"}  # information only, no rule depends on it
    assert r.origins["rules.severity.pse"].file == "normes/lumiris_maison.yaml"
    assert r.origins["rules.severity.scan_flag_mismatch"].file == "normes/lumiris_maison.yaml"
    assert r.profile.rules.severity["scan_interlaced"][0].else_ == "minor"
    assert r.profile.rules.severity["scan_interlaced"][0].source.startswith("Arte V2-01-03 §3.2.2.1")
    assert "V2-01-03" in r.profile.meta.source_document
    assert r.origins["format.delivery.scan"].source.startswith("Arte V2-01-03 §3.2.2.1")
    assert {(c.path, c.replaced_value, c.value, c.replaced_file) for c in r.conflicts} == {
        ("video.y_tolerance_low_pct", -5.0, -1.0, "normes/ebu_r103.yaml"),
        ("video.y_tolerance_high_pct", 105.0, 103.0, "normes/ebu_r103.yaml"),
        ("audio.loudness.long.integrated_tolerance_lu", 0.2, 1.0, "normes/ebu_r128.yaml"),
    }


def test_france_tv_is_draft() -> None:
    r = resolve_profile(PROFILES / "france_tv_hd.yaml")
    assert r.profile.meta.status == "draft"
    assert r.profile.audio.true_peak_max_dbtp == -3.0
    assert r.origins["audio.true_peak_max_dbtp"].replaced == [{"file": "normes/ebu_r128.yaml", "value": -1.0}]


# normes/glossaire.yaml (meta.kind: glossary) is vocabulary for draft-profile, not a norm.
@pytest.mark.parametrize("path", [p for p in sorted(REPO_NORMS.glob("*.yaml")) if is_norm(read_yaml(p))],
                         ids=lambda p: p.name)
def test_norms_cite_every_value(path: Path) -> None:
    norm = load_norm(path)
    assert norm.meta.kind == "norm" and norm.meta.document.version


def test_effective_json_is_deterministic() -> None:
    a = resolve_profile(PROFILES / "arte_hd_sdr.yaml")
    b = resolve_profile(PROFILES / "arte_hd_sdr.yaml")
    assert a.dumps() == b.dumps()
    data = json.loads(a.dumps())
    assert list(data) == sorted(data) and re.search(r"T\d{2}:\d{2}", a.dumps()) is None  # no timestamp
    back = from_json(data, Path("effective_profile.json"))
    assert back.fingerprint == a.fingerprint and back.profile == a.profile


def test_effective_json_tampered(tmp_path: Path) -> None:
    data = json.loads(resolve_profile(PROFILES / "arte_hd_sdr.yaml").dumps())
    data["values"]["audio"]["true_peak_max_dbtp"] = -2.0
    with pytest.raises(ProfileError, match="empreinte"):
        from_json(data, tmp_path / "effective_profile.json")


# --- synthetic norms ---------------------------------------------------------------------------


def _norm(folder: Path, name: str, body: dict, sources: dict | None = None, extends: list[str] | None = None) -> None:
    raw = {"meta": {"kind": "norm", "name": name, "document": {"title": f"Norme {name}", "version": "1"}}}
    if extends:
        raw["meta"]["extends"] = extends
    raw |= body
    raw["sources"] = sources if sources is not None else {p: f"{name} §1" for p, _ in leaves(body)}
    (folder / f"{name}.yaml").write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")


@pytest.fixture
def lab(tmp_path: Path):
    """tmp/profiles/ + tmp/normes/ (found as the sibling of the profile folder), with lumiris_maison."""
    (tmp_path / "profiles").mkdir()
    norms = tmp_path / "normes"
    norms.mkdir()
    shutil.copyfile(REPO_NORMS / "lumiris_maison.yaml", norms / "lumiris_maison.yaml")

    def profile(extends: list[str], mutate=None) -> Path:
        raw = yaml.safe_load((TEST_PROFILES / "test_classic.yaml").read_text(encoding="utf-8"))
        raw["meta"]["extends"] = extends
        if mutate:
            mutate(raw)
        path = tmp_path / "profiles" / "p.yaml"
        path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
        return path

    return norms, profile


def _drop(*paths: str):
    def mutate(raw):
        for dotted in paths:
            *parents, last = dotted.split(".")
            node = raw
            for p in parents:
                node = node[p]
            del node[last]
    return mutate


def test_priority_last_layer_wins(lab) -> None:
    norms, profile = lab
    _norm(norms, "a", {"audio": {"true_peak_max_dbtp": -1.0, "silence_dbfs": -50.0}})
    _norm(norms, "b", {"audio": {"true_peak_max_dbtp": -2.0}})
    house = yaml.safe_load((norms / "lumiris_maison.yaml").read_text(encoding="utf-8"))
    house["audio"] = {"true_peak_max_dbtp": -3.0}
    house["sources"]["audio.true_peak_max_dbtp"] = "Lumiris : test"
    (norms / "lumiris_maison.yaml").write_text(yaml.safe_dump(house, allow_unicode=True), encoding="utf-8")

    r = resolve_profile(profile(["a", "b", "lumiris_maison"],
                                _drop("audio.true_peak_max_dbtp", "audio.silence_dbfs")))
    assert r.profile.audio.true_peak_max_dbtp == -3.0  # lumiris_maison > b > a
    assert r.origins["audio.true_peak_max_dbtp"].file == "normes/lumiris_maison.yaml"
    assert r.profile.audio.silence_dbfs == -50.0 and r.origins["audio.silence_dbfs"].source == "a §1"
    peaks = [(c.replaced_file, c.file) for c in r.conflicts if c.path == "audio.true_peak_max_dbtp"]
    assert peaks == [("normes/a.yaml", "normes/b.yaml"), ("normes/b.yaml", "normes/lumiris_maison.yaml")]

    r = resolve_profile(profile(["a", "b", "lumiris_maison"]))  # the profile itself says -3.0 (CST RT-017)
    assert r.origins["audio.true_peak_max_dbtp"].file == "profiles/p.yaml"
    assert [c.replaced_file for c in r.conflicts if c.path == "audio.true_peak_max_dbtp"] == [
        "normes/a.yaml", "normes/b.yaml"]  # lumiris_maison said -3.0 too: restated, not a conflict


def test_conflict_listed_with_both_values(lab) -> None:
    norms, profile = lab
    _norm(norms, "a", {"video": {"y_tolerance_high_pct": 105.0}})
    r = resolve_profile(profile(["a", "lumiris_maison"]))
    [c] = [c for c in r.conflicts if c.path == "video.y_tolerance_high_pct"]
    assert (c.replaced_value, c.replaced_file, c.value, c.file) == (105.0, "normes/a.yaml", 103.0, "profiles/p.yaml")


def test_missing_norm_refused(lab) -> None:
    _, profile = lab
    with pytest.raises(ProfileError) as exc:
        resolve_profile(profile(["absente", "lumiris_maison"]))
    assert any("norme « absente » introuvable" in m for m in exc.value.messages)


def test_cycle_refused(lab) -> None:
    norms, profile = lab
    _norm(norms, "a", {"audio": {"silence_dbfs": -50.0}}, extends=["b"])
    _norm(norms, "b", {"audio": {"silence_dbfs": -55.0}}, extends=["a"])
    path = profile(["a", "lumiris_maison"])
    with pytest.raises(ProfileError) as exc:
        resolve_profile(path)
    assert any("cycle d'héritage : a → b → a" in m for m in exc.value.messages)
    result = runner.invoke(app, ["validate-profile", str(path)])
    assert result.exit_code == EXIT_USAGE and "cycle" in result.output


def test_inherited_null_refused(lab) -> None:
    norms, profile = lab
    _norm(norms, "a", {"audio": {"silence_max_seconds": None}},
          sources={"audio.silence_max_seconds": "A VERIFIER : paragraphe à confirmer"})
    r = resolve_profile(profile(["a", "lumiris_maison"], _drop("audio.silence_max_seconds")))
    assert "audio.silence_max_seconds" in null_fields(r.profile)
    problems = pipeline.preflight(r.profile, r.profile.audio.groups)
    assert any("audio.silence_max_seconds » vaut null" in p for p in problems)


def test_norm_value_needs_a_source(lab) -> None:
    norms, _ = lab
    _norm(norms, "a", {"audio": {"silence_dbfs": -50.0}}, sources={})
    with pytest.raises(ProfileError) as exc:
        load_norm(norms / "a.yaml")
    assert any("audio.silence_dbfs" in m and "sans source" in m for m in exc.value.messages)


def test_norm_typo_refused(lab) -> None:
    norms, _ = lab
    _norm(norms, "a", {"audio": {"silence_dbfss": -50.0}})
    with pytest.raises(ProfileError) as exc:
        load_norm(norms / "a.yaml")
    assert any("champ inconnu « audio.silence_dbfss »" in m for m in exc.value.messages)


def test_house_rules_last(lab) -> None:
    norms, profile = lab
    _norm(norms, "a", {"audio": {"silence_dbfs": -50.0}})
    with pytest.raises(ProfileError) as exc:
        resolve_profile(profile(["lumiris_maison", "a"]))
    assert any("lumiris_maison" in m and "dernière" in m for m in exc.value.messages)


def test_norm_wrong_type_refused(lab) -> None:
    norms, profile = lab
    _norm(norms, "a", {"structure": {"freeze": {"threshold": "beaucoup"}}})
    with pytest.raises(ProfileError):
        load_norm(norms / "a.yaml")  # a norm is checked on its own, before any merge


def test_validated_needs_who_and_when(lab) -> None:
    _, profile = lab
    with pytest.raises(ProfileError) as exc:
        resolve_profile(profile([], _drop("meta.validated_by")))
    assert any("validated_by" in m for m in exc.value.messages)


def test_cli_validate_and_explain() -> None:
    result = runner.invoke(app, ["validate-profile", str(ROOT / "normes" / "ebu_r128.yaml")])
    assert result.exit_code == 0 and "Norme valide" in result.output
    result = runner.invoke(app, ["validate-profile", str(PROFILES / "arte_hd_sdr.yaml")])
    assert result.exit_code == 0 and "validé par Damien" in result.output
    result = runner.invoke(app, ["explain-profile", str(PROFILES / "arte_hd_sdr.yaml")], env={"COLUMNS": "250"})
    assert result.exit_code == 0, result.output
    text = " ".join(result.output.split())
    assert "Conflits" in text and "video.y_tolerance_low_pct" in text and "normes/ebu_r103.yaml" in text
    assert "audio.true_peak_max_dbtp" in text and "normes/ebu_r128.yaml" in text


# --- scan detection ----------------------------------------------------------------------------


SCAN = ScanDetection(comb_ratio_min=0.9, motion_min=1.0, interlaced_min_pct=50, progressive_max_pct=10,
                     min_moving_frames=3)


def _video(field_order: str, flag: str) -> VideoInfo:
    return VideoInfo(stream_index=0, codec_name="prores", profile="HQ", pix_fmt="yuv422p10le", width=1920,
                     height=1080, r_frame_rate="25/1", avg_frame_rate="25/1", fps="25/1", field_order=field_order,
                     scan_flag=flag, color_primaries=None, color_transfer=None, color_space=None,
                     color_range=None, duration_s=None, nb_frames=None, nb_frames_source=None)


def test_scan_detection_rules() -> None:
    nan = float("nan")
    progressive = detect(_video("progressive", "progressive"), [0.7, 0.7, 0.7, 0.7], [nan, 5, 5, 5], SCAN)
    assert (progressive.detected, progressive.moving_frames, progressive.agrees) == ("progressive", 3, True)
    combed = detect(_video("progressive", "progressive"), [1.1, 1.1, 1.1, 0.7], [nan, 5, 5, 5], SCAN)
    assert combed.detected == "interlaced" and combed.agrees is False  # flag and pictures disagree
    still = detect(_video("tt", "interlaced"), [1.1] * 4, [nan, 0, 0, 0], SCAN)
    assert still.detected == "undetermined" and still.agrees is None  # nothing moves: no evidence


def test_france_tv_a_verifier_never_about_norms() -> None:
    """« A VERIFIER » means: no citation of the client's document, never « differs from a norm »."""
    for line in (PROFILES / "france_tv_hd.yaml").read_text(encoding="utf-8").splitlines():
        if "A VERIFIER" in line:
            assert not any(n in line for n in ("R103", "R 103", "R128", "R 128")), line
