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
    """A BT.601 picture is measured with its own matrix whatever the profile asks (a profile in
    BT.709 only gets a tag anomaly), and the 16:9 picture aspect comes from the anamorphic pixels
    (720 x 576, pixels 64:45)."""
    sd = _analyse(fixtures_dir, tmp_path, "sd_pal_169.mov", _sd_profile(tmp_path, "bt470bg"))
    hd = _analyse(fixtures_dir, tmp_path, "sd_pal_169.mov", _sd_profile(tmp_path, "bt709"))
    assert _video(sd) == _video(hd)
    assert max(f["rgb_out_pct"] for f in _video(sd)) < 2  # about 60 % with the BT.709 matrix
    for out in (sd, hd):
        m = json.loads((out / wd.MEASUREMENTS).read_text(encoding="utf-8"))
        assert m["video_settings"]["matrix"] == "bt470bg" and m["video"]["first_field"] == "top"
    tags = lambda out: {e["title"] for e in json.loads((out / wd.EVENTS).read_text(encoding="utf-8"))["events"]  # noqa: E731
                        if e["type"] == "format_color_tags"}
    assert not tags(sd) and tags(hd) == {"Colorimétrie : matrice", "Colorimétrie : primaires"}
    st = json.loads((sd / wd.STRUCTURE).read_text(encoding="utf-8"))
    assert st["letterbox"]["dominant_aspect"] == pytest.approx(1.78, abs=0.01)
    probe = json.loads((sd / wd.PROBE).read_text(encoding="utf-8"))
    assert probe["video"]["sar"] == "64:45"
    assert "matrice bt470bg (balise du fichier)" in (sd / wd.REPORT_MD).read_text(encoding="utf-8")


def test_file_matrix() -> None:
    """The tag when it names a supported matrix, else the standard of the line count."""
    assert formats.file_matrix("bt470bg", 1080) == ("bt470bg", "balise du fichier")
    assert formats.file_matrix(None, 576)[0] == formats.file_matrix("unknown", 576)[0] == "bt470bg"
    assert formats.file_matrix(None, 480)[0] == formats.file_matrix("gbr", 486)[0] == "smpte170m"
    assert formats.file_matrix("gbr", 360) == ("bt709", "fichier RVB, sans matrice : standard des 360 lignes")
    assert formats.file_matrix(None, 2160)[0] == "bt709"
    assert not formats.matrix_measurable("smpte240m") and formats.matrix_measurable("gbr")


def test_coherent_tags() -> None:
    assert formats.coherent_tags("color_space", True, 1080)[0] == ("gbr",)
    assert formats.coherent_tags("color_space", False, 576)[0] == ("bt470bg", "smpte170m")
    assert formats.coherent_tags("color_transfer", False, 576)[0] == ("bt709", "smpte170m")
    assert formats.coherent_tags("color_primaries", True, 1080)[0] == ("bt709",)


def test_dv_pal(fixtures_dir, tmp_path) -> None:
    """DV PAL: 4:2:0 8 bits, bottom field first, decoded and measured."""
    out = _analyse(fixtures_dir, tmp_path, "sd_dv.mov", _sd_profile(tmp_path, "bt470bg"))
    m = json.loads((out / wd.MEASUREMENTS).read_text(encoding="utf-8"))
    assert m["integrity"]["frames_decoded"] == 50 and m["integrity"]["errors"] == []
    assert m["video"]["first_field"] == "bottom"
    probe = json.loads((out / wd.PROBE).read_text(encoding="utf-8"))
    assert (probe["video"]["bit_depth"], probe["video"]["sampling"]) == (8, "4:2:0")
