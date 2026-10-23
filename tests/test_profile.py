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
    # A complete profile (france_tv_hd.yaml now inherits most of its values from normes/).
    raw = yaml.safe_load((TEST_PROFILES / "test_classic.yaml").read_text(encoding="utf-8"))
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


def test_prefilter_needs_kernel(tmp_path: Path) -> None:
    def bad(raw):
        del raw["video"]["prefilter_taps"]

    errors = _errors(_mutated(tmp_path, bad))
    assert any("prefilter_taps" in e for e in errors)


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


def test_severity_rule_needs_a_source(tmp_path: Path) -> None:
    def bad(raw):
        del raw["rules"]["severity"]["pse"][0]["source"]

    errors = _errors(_mutated(tmp_path, bad))
    assert any("rules.severity.pse[0].source" in e for e in errors)


@pytest.mark.parametrize("source", ["DEDUIT", "deduit (Arte §3.3.2.5)"])
def test_deduced_rule_capped_at_minor(tmp_path: Path, source: str) -> None:
    def bad(raw):
        raw["rules"]["severity"]["freeze"] = [{"else": "major", "source": source}]

    errors = _errors(_mutated(tmp_path, bad))
    assert any("DEDUIT ne peut pas dépasser minor" in e and "rules.severity.freeze" in e for e in errors)
    result = runner.invoke(app, ["validate-profile", str(tmp_path / "profile.yaml")])
    assert result.exit_code != 0 and "dépasser minor" in " ".join(result.output.split())


def test_arte_severity_calibration() -> None:
    p = load_profile(PROFILES / "arte_hd_sdr.yaml")
    sev = {name: [r.severity for r in chain] for name, chain in p.rules.severity.items()}
    for name in ("freeze", "audio_silence", "audio_short_term_excursion", "duplicate_frame"):
        assert sev[name] == ["minor"], name
    assert sev["pse"] == ["major"] and p.rules.severity["pse"][0].source.startswith("Lumiris")
    for chain in p.rules.severity.values():  # every major / blocking rule cites a document, never DEDUIT
        for rule in chain:
            if rule.severity in ("blocking", "major"):
                assert rule.source.startswith(("Arte §", "Lumiris")), rule


def test_validate_profile_warns_on_unsourced_major() -> None:
    result = runner.invoke(app, ["validate-profile", str(PROFILES / "france_tv_hd.yaml")])
    assert result.exit_code == 0
    assert "sans document source" in " ".join(result.output.split())
