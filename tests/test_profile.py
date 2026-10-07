from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from pad_checker.cli import app
from pad_checker.rules.profile import ProfileError, load_profile, null_fields

from conftest import PROFILES, TEST_PROFILES

runner = CliRunner()

ALL_PROFILES = sorted(PROFILES.glob("*.yaml")) + sorted(TEST_PROFILES.glob("*.yaml"))


@pytest.mark.parametrize("path", ALL_PROFILES, ids=lambda p: p.name)
def test_shipped_profiles_are_valid(path: Path) -> None:
    load_profile(path)


def test_arte_values() -> None:
    p = load_profile(PROFILES / "arte_hd_sdr.yaml")
    assert p.structure.leaders == "none"
    assert p.audio.true_peak_max_dbtp == -1.0
    assert [g.name for g in p.audio.groups] == ["VO", "VF", "VI"]
    assert p.audio.loudness.short is not None and p.audio.loudness.short.integrated_tolerance_lu == 0.5
    assert null_fields(p) == []
    assert (p.structure.black.head_max_seconds, p.structure.black.tail_max_seconds) == (2.0, 5.0)


def test_france_tv_values() -> None:
    p = load_profile(PROFILES / "france_tv_hd.yaml")
    assert p.structure.leaders == "classic"
    assert p.audio.true_peak_max_dbtp == -3.0
    assert p.audio.loudness.short is None
    assert p.format.fps_allowed == ["25/1"]


def _mutated(tmp_path: Path, mutate) -> Path:
    raw = yaml.safe_load((PROFILES / "france_tv_hd.yaml").read_text(encoding="utf-8"))
    mutate(raw)
    out = tmp_path / "profile.yaml"
    out.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return out


def _errors(path: Path) -> list[str]:
    with pytest.raises(ProfileError) as exc:
        load_profile(path)
    return exc.value.messages


def test_typo_names_the_field(tmp_path: Path) -> None:
    def typo(raw):
        raw["video"]["y_max_legall"] = raw["video"].pop("y_max_legal")

    errors = _errors(_mutated(tmp_path, typo))
    assert any("video.y_max_legall" in e and "inconnu" in e for e in errors)
    assert any("video.y_max_legal" in e and "manquant" in e for e in errors)


def test_unknown_event_type_is_rejected(tmp_path: Path) -> None:
    def typo(raw):
        raw["rules"]["severity"]["white_clp"] = raw["rules"]["severity"].pop("white_clip")

    errors = _errors(_mutated(tmp_path, typo))
    assert any("rules.severity.white_clp" in e for e in errors)


def test_severity_expression_unknown_name(tmp_path: Path) -> None:
    def bad(raw):
        raw["rules"]["severity"]["white_clip"][0]["if"] = "worst_valeur > 1004"

    errors = _errors(_mutated(tmp_path, bad))
    assert any("worst_valeur" in e for e in errors)


def test_severity_expression_rejects_code(tmp_path: Path) -> None:
    def bad(raw):
        raw["rules"]["severity"]["white_clip"][0]["if"] = "__import__('os').system('echo')"

    errors = _errors(_mutated(tmp_path, bad))
    assert any("rules.severity.white_clip" in e for e in errors)


def test_severity_chain_must_end_with_else(tmp_path: Path) -> None:
    def bad(raw):
        raw["rules"]["severity"]["white_clip"].pop()

    errors = _errors(_mutated(tmp_path, bad))
    assert any("dernière règle" in e for e in errors)


def test_bad_timecode(tmp_path: Path) -> None:
    def bad(raw):
        raw["structure"]["timecode"]["file_start"] = "10:00:00"

    errors = _errors(_mutated(tmp_path, bad))
    assert any("structure.timecode.file_start" in e for e in errors)


def test_short_loudness_requires_threshold(tmp_path: Path) -> None:
    def bad(raw):
        raw["audio"]["loudness"]["short"] = dict(raw["audio"]["loudness"]["long"])

    errors = _errors(_mutated(tmp_path, bad))
    assert any("long_program_min_seconds" in e for e in errors)


def test_track_in_two_groups(tmp_path: Path) -> None:
    def bad(raw):
        raw["audio"]["groups"][1]["tracks"] = [2, 3]

    errors = _errors(_mutated(tmp_path, bad))
    assert any("plusieurs groupes" in e for e in errors)


def test_cli_validate_ok() -> None:
    result = runner.invoke(app, ["validate-profile", str(PROFILES / "france_tv_hd.yaml")])
    assert result.exit_code == 0, result.output
    assert "Profil valide" in result.output


def test_cli_validate_lists_null_fields(tmp_path: Path) -> None:
    def open_value(raw):
        raw["structure"]["black"]["head_min_seconds"] = None

    result = runner.invoke(app, ["validate-profile", str(_mutated(tmp_path, open_value))])
    assert result.exit_code == 0, result.output
    assert "structure.black.head_min_seconds" in result.output


def test_cli_validate_typo(tmp_path: Path) -> None:
    def typo(raw):
        raw["format"]["pix_fmtt"] = raw["format"].pop("pix_fmt")

    result = runner.invoke(app, ["validate-profile", str(_mutated(tmp_path, typo))])
    assert result.exit_code == 1
    assert "format.pix_fmtt" in result.output


def test_cli_validate_missing_file(tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate-profile", str(tmp_path / "absent.yaml")])
    assert result.exit_code == 1
    assert "introuvable" in result.output
