"""SD (Phase 6): 625-line files, BT.601 matrix, anamorphic pixels, DV."""

from __future__ import annotations

import json

import pytest
import yaml
from typer.testing import CliRunner

from pad_guard import formats, workdir as wd
from pad_guard.cli import app

from conftest import TEST_PROFILES

pytestmark = pytest.mark.fixtures

CLASSIC = TEST_PROFILES / "test_classic.yaml"


def _sd_profile(tmp_path, matrix: str):
    raw = yaml.safe_load(CLASSIC.read_text(encoding="utf-8"))
    raw["format"].update(width=720, height=576, color_primaries=matrix, color_space=matrix,
                         letterbox={"check": True, "formats": [], "tolerance_lines": 2})
    raw["rules"]["severity"]["letterbox"] = [{"else": "minor", "source": "profil de test"}]
    path = tmp_path / f"sd_{matrix}.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _analyse(fixtures_dir, tmp_path, name, profile):
    out = tmp_path / f"{name}_{profile.stem}"
    result = CliRunner().invoke(app, ["analyze", str(fixtures_dir / name), "--profile", str(profile),
                                      "--out", str(out), "--no-thumbnails"])
    assert result.exception is None or isinstance(result.exception, SystemExit), result.output
    return out


def _video(out):
    return [json.loads(line) for line in (out / "measurements_video.jsonl").read_text(encoding="utf-8").splitlines()]


def test_bt601_matrix_is_known() -> None:
    """Coefficients of BT.601 (A VERIFIER: source to add to normes/sources/TV)."""
    assert formats.MATRICES["bt470bg"] == formats.MATRICES["smpte170m"] == (0.299, 0.114)


def test_sd_pal_169_with_its_matrix(fixtures_dir, tmp_path) -> None:
    """A BT.601 picture measured with the BT.601 matrix: fewer pixels out of gamut than with BT.709,
    and the 16:9 picture aspect comes from the anamorphic pixels (720 x 576, pixels 64:45)."""
    sd = _analyse(fixtures_dir, tmp_path, "sd_pal_169.mov", _sd_profile(tmp_path, "bt470bg"))
    hd = _analyse(fixtures_dir, tmp_path, "sd_pal_169.mov", _sd_profile(tmp_path, "bt709"))
    rgb_sd = max(f["rgb_out_pct"] for f in _video(sd))
    rgb_hd = max(f["rgb_out_pct"] for f in _video(hd))
    assert rgb_sd < rgb_hd
    st = json.loads((sd / wd.STRUCTURE).read_text(encoding="utf-8"))
    assert st["letterbox"]["dominant_aspect"] == pytest.approx(1.78, abs=0.01)
    m = json.loads((sd / wd.MEASUREMENTS).read_text(encoding="utf-8"))
    assert m["video_settings"]["matrix"] == "bt470bg" and m["video"]["first_field"] == "top"
    probe = json.loads((sd / wd.PROBE).read_text(encoding="utf-8"))
    assert probe["video"]["sar"] == "64:45"


def test_dv_pal(fixtures_dir, tmp_path) -> None:
    """DV PAL: 4:2:0 8 bits, bottom field first, decoded and measured."""
    out = _analyse(fixtures_dir, tmp_path, "sd_dv.mov", _sd_profile(tmp_path, "bt470bg"))
    m = json.loads((out / wd.MEASUREMENTS).read_text(encoding="utf-8"))
    assert m["integrity"]["frames_decoded"] == 50 and m["integrity"]["errors"] == []
    assert m["video"]["first_field"] == "bottom"
    probe = json.loads((out / wd.PROBE).read_text(encoding="utf-8"))
    assert (probe["video"]["bit_depth"], probe["video"]["sampling"]) == (8, "4:2:0")
