"""Coding range and R'G'B' sources (Phase 6): thresholds apply on the right levels."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from pad_guard import workdir as wd
from pad_guard.cli import app
from pad_guard.decode.video import Picture, VideoDecoder, _narrow12, _signal, picture_of

from conftest import TEST_PROFILES

CLASSIC = TEST_PROFILES / "test_classic.yaml"


def test_picture_of() -> None:
    assert picture_of("yuv422p10le", "tv", "bt709") is None
    assert picture_of("yuv422p10le", None, "bt709") is None
    assert picture_of("yuv422p10le", "pc", "bt709") == Picture(full_range=True)
    assert picture_of("yuvj420p", None, "bt709") == Picture(full_range=True)
    assert picture_of("gbrp10le", None, "bt709") == Picture(full_range=True)
    assert picture_of("gbrp10le", "tv", "bt709") == Picture(full_range=False)


def test_full_range_codes_land_on_the_narrow_levels() -> None:
    """BT.2100 Table 9 full range -> BT.709 narrow range (12-bit codes, scale 4): black 0 -> 64,
    white 1023 -> 940, chroma 512 -> 512, 8-bit 255 -> 940."""
    y = _narrow12(_signal(np.array([0, 1023], np.uint16), 10, True, False), False)
    c = _narrow12(_signal(np.array([0, 512, 1023], np.uint16), 10, True, True), True)
    assert (y / 4).tolist() == [64.0, 940.0]
    assert (c / 4).tolist() == [63.5, 512.0, 959.5]  # full-range chroma spans -512/1023 to +511/1023
    assert (_narrow12(_signal(np.array([255], np.uint8), 8, True, False), False) / 4).tolist() == [940.0]
    # Narrow range R'G'B' (tagged tv): 64 and 940 are black and white.
    assert (_narrow12(_signal(np.array([64, 940], np.uint16), 10, False, False), False) / 4).tolist() == [64.0, 940.0]


@pytest.fixture(scope="module")
def analysed(fixtures_dir, tmp_path_factory):
    cache: dict[str, Path] = {}

    def get(name: str) -> tuple[list[dict], dict]:
        if name not in cache:
            out = tmp_path_factory.mktemp(name.replace(".", "_"))
            CliRunner().invoke(app, ["analyze", str(fixtures_dir / name), "--profile", str(CLASSIC),
                                     "--out", str(out), "--no-thumbnails"])
            cache[name] = out
        out = cache[name]
        events = json.loads((out / wd.EVENTS).read_text(encoding="utf-8"))["events"]
        first = json.loads((out / "measurements_video.jsonl").read_text(encoding="utf-8").splitlines()[0])
        return events, first

    return get


@pytest.mark.fixtures
def test_full_range_file_measured_on_its_range(analysed) -> None:
    """H.264 yuvj420p tagged pc: white at 1023 is 100 % (no white clip), the tag differs from the
    profile (format), and the content is not flagged."""
    events, first = analysed("fmt_h264_full.mp4")
    types = {e["type"] for e in events}
    assert "white_clip" not in types and "black_crush" not in types
    assert not types & {"range_content_mismatch", "range_tag_suspect"}
    assert [e["value_text"] for e in events if e["title"] == "Plage"] == ["pc"]
    assert first["y_max"] == 940.0 and first["y_min"] == 64.0


@pytest.mark.fixtures
def test_full_range_content_tagged_narrow(analysed) -> None:
    """Full-range content in a ProRes tagged tv (ProRes clips to 4-1019): flagged as such."""
    events, first = analysed("fmt_full_as_tv.mov")
    mismatch = [e for e in events if e["type"] == "range_content_mismatch"]
    assert [(e["severity"], e["value_text"]) for e in mismatch] == [
        ("major", "100,0 % des images aux bornes de la plage numérique")]
    assert (first["y_min"], first["y_max"]) == (4, 1019)


@pytest.mark.fixtures
def test_rgb_source(analysed, fixtures_dir) -> None:
    """DNxHR 444 R'G'B' (gbrp10le, full range): converted to narrow Y'CbCr 4:4:4 before measuring."""
    frame = next(iter(VideoDecoder(fixtures_dir / "fmt_dnxhr444_rgb.mov",
                                   picture=picture_of("gbrp10le", "pc", "bt709")).frames()))
    assert (frame.scale, frame.hsub, frame.vsub) == (4, 1, 1)
    assert 64 * 4 <= int(frame.y.min()) and int(frame.y.max()) <= 940 * 4
    events, first = analysed("fmt_dnxhr444_rgb.mov")
    assert not {e["type"] for e in events} & {"white_clip", "black_crush", "gamut", "range_content_mismatch"}
    assert first["rgb_out_pct"] == 0.0
