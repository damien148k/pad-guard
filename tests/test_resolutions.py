"""Any resolution (Phase 6): UHD, 4K DCI, the active area and the thumbnails."""

from __future__ import annotations

import json
from fractions import Fraction

import pytest
import yaml
from typer.testing import CliRunner

from pad_guard import workdir as wd
from pad_guard.cli import app
from pad_guard.decode.video import read_frames
from pad_guard.measure.video import VideoLimits
from pad_guard.report import thumbnails
from pad_guard.rules.profile import load_profile
from pad_guard.structure import letterbox as lb
from pad_guard.structure.models import LetterboxSample

from conftest import TEST_PROFILES

CLASSIC = TEST_PROFILES / "test_classic.yaml"


def test_aspect_with_pixel_ratio() -> None:
    full = LetterboxSample(frame=0, top=0, bottom=575, left=0, right=719)
    assert lb.aspect(full) == 1.25 and lb.aspect(full, lb.sar_of("64:45")) == 1.78  # SD 16:9 anamorphic
    assert lb.sar_of(None) == 1 and lb.sar_of("0:1") == 1 and lb.sar_of("x") == 1
    assert lb.aspect(LetterboxSample(frame=0, top=276, bottom=1883, left=0, right=3839)) == 2.39


@pytest.mark.parametrize(("width", "k"), [(720, 1), (1920, 3), (2048, 3), (3840, 6), (4096, 6)])
def test_thumbnail_scale(width, k) -> None:
    assert thumbnails.scale_for(width) == k


@pytest.mark.fixtures
def test_uhd_active_area_recorded(fixtures_dir, tmp_path) -> None:
    """A profile without a format table records the active area of a UHD 2.39 file, compares nothing."""
    raw = yaml.safe_load(CLASSIC.read_text(encoding="utf-8"))
    raw["format"]["letterbox"] = {"check": True, "formats": [], "tolerance_lines": 2}
    raw["rules"]["severity"]["letterbox"] = [{"else": "minor", "source": "profil de test"}]
    profile = tmp_path / "area.yaml"
    profile.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    out = tmp_path / "o"
    result = CliRunner().invoke(app, ["analyze", str(fixtures_dir / "fmt_uhd_239.mov"), "--profile", str(profile),
                                      "--out", str(out), "--no-thumbnails"])
    assert result.exception is None or isinstance(result.exception, SystemExit), result.output
    st = json.loads((out / wd.STRUCTURE).read_text(encoding="utf-8"))
    check = next(c for c in st["checks"] if c["id"] == "letterbox")
    assert check["status"] == "ok" and check["expected"].startswith("relevé seulement")
    # 1608 active lines from line 276; ProRes blocks ring a few lines into the black band above.
    dom = st["letterbox"]["dominant"]
    assert 270 <= dom["top"] <= 276 and dom["bottom"] == 1883 and (dom["left"], dom["right"]) == (0, 3839)
    assert 2.37 <= st["letterbox"]["dominant_aspect"] <= 2.39 and "× 3840 px" in check["actual"]
    m = json.loads((out / wd.MEASUREMENTS).read_text(encoding="utf-8"))
    assert m["video"]["frames"] == 10 and m["integrity"]["frames_decoded"] == 10
    events = json.loads((out / wd.EVENTS).read_text(encoding="utf-8"))["events"]
    assert [e["value_text"] for e in events if e["type"] == "format_resolution"] == ["3840x2160"]


@pytest.mark.fixtures
def test_dci4k_thumbnail_and_measures(fixtures_dir) -> None:
    limits = VideoLimits.from_profile(load_profile(CLASSIC))
    (frame,) = read_frames(fixtures_dir / "fmt_dci4k.mov", [3])
    picture = thumbnails.render(frame, limits, "white_clip")
    assert picture.shape[1] == 2 * (4096 // 6) + 8 and picture.shape[0] == 2160 // 6
    assert Fraction(4096, 2160) > Fraction(16, 9)
