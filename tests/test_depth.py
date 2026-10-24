"""Bit depth and chroma sampling (Phase 6): 8, 10 and 12 bits; 4:2:0, 4:2:2 and 4:4:4; alpha."""

from __future__ import annotations

import dataclasses
import json

import numpy as np
import pytest
from typer.testing import CliRunner

from pad_guard import workdir as wd
from pad_guard.cli import app
from pad_guard.decode.video import VideoFrame
from pad_guard.measure.video import FrameMeter, VideoLimits, out_of_range_masks
from pad_guard.rules.profile import load_profile

from conftest import PROFILES, TEST_PROFILES

ARTE = PROFILES / "arte_hd_sdr.yaml"
CLASSIC = TEST_PROFILES / "test_classic.yaml"


@pytest.fixture(scope="module")
def limits() -> VideoLimits:
    """Arte bounds without the prefilter: its rounding is finer in 12 bits, and in 4:4:4 it runs on
    full-width chroma, so the equivalences below hold for the unfiltered measures only."""
    return dataclasses.replace(VideoLimits.from_profile(load_profile(ARTE)), prefilter_taps=None)


def _frame(h: int = 64, w: int = 96, seed: int = 3) -> VideoFrame:
    """A 10-bit 4:2:2 frame with values across the whole range (out of range included)."""
    rng = np.random.default_rng(seed)
    y = rng.integers(0, 1024, (h, w), dtype=np.uint16)
    cb = rng.integers(64, 961, (h, w // 2), dtype=np.uint16)
    cr = rng.integers(64, 961, (h, w // 2), dtype=np.uint16)
    return VideoFrame(index=1, y=y, cb=cb, cr=cr)


def _measure(limits, frame, previous=None) -> dict:
    return FrameMeter(limits, strip_rows=16).measure(frame, previous)


def test_12_bit_is_the_10_bit_measure_times_4(limits) -> None:
    """The same picture in 12 bits (10-bit values x 4): the same measures, written in 10-bit codes."""
    f10, p10 = _frame(), _frame(seed=4)
    f12 = VideoFrame(index=1, y=f10.y * 4, cb=f10.cb * 4, cr=f10.cr * 4, scale=4)
    m10 = _measure(limits, f10, p10.y)
    m12 = _measure(limits, f12, p10.y * 4)
    assert m12 == m10


def test_12_bit_thresholds_are_the_10_bit_ones_times_4(limits) -> None:
    """The 103 % tolerance is code 967 in 10 bits, 3868 in 12 bits: 3869 is out, which a 10-bit
    file cannot say (decision of Damien: thresholds x 4 exactly)."""
    hi = limits.y_tolerance[1]
    assert hi == 967
    y = np.full((16, 32), 3868, np.uint16)
    y[:, :8] = 3869  # 25 % of the picture
    chroma = np.full((16, 16), 2048, np.uint16)
    m = _measure(limits, VideoFrame(index=0, y=y, cb=chroma, cr=chroma, scale=4))
    assert m["y_above_pct"] == 25.0 and m["y_max"] == 967.25
    masks = out_of_range_masks(VideoFrame(index=0, y=y, cb=chroma, cr=chroma, scale=4), limits)
    assert masks["y_above"].mean() == 0.25


def test_8_bit_is_converted_to_10_bits(fixtures_dir, tmp_path) -> None:
    """An 8-bit file is measured in 10-bit codes (x 4): Y = 16 (8 bits) is 64, the legal black."""
    from pad_guard.decode.video import VideoDecoder

    frames = list(VideoDecoder(fixtures_dir / "fmt_dnxhr_hq_2k.mov").frames())
    assert frames[0].y.dtype == np.uint16 and frames[0].scale == 1
    assert int(frames[0].y.max()) % 4 == 0 and frames[0].y.shape == (1556, 2048)


def test_444_equals_422_with_the_same_chroma(limits) -> None:
    """4:4:4 chroma equal to the interpolated 4:2:2 chroma gives the same measures."""
    f = _frame()
    # Even chroma values: the mean of two neighbours is an integer, so 4:4:4 can hold it exactly.
    f = VideoFrame(index=1, y=f.y, cb=f.cb // 2 * 2, cr=f.cr // 2 * 2)

    def up(c):
        out = np.empty((c.shape[0], c.shape[1] * 2), np.uint16)
        out[:, 0::2] = c
        out[:, 1:-1:2] = (c[:, :-1].astype(np.uint32) + c[:, 1:]) // 2
        out[:, -1] = c[:, -1]
        return out
    f444 = VideoFrame(index=1, y=f.y, cb=up(f.cb), cr=up(f.cr), hsub=1)
    a, b = _measure(limits, f), _measure(limits, f444)
    assert a["rgb_out_pct"] == b["rgb_out_pct"]
    assert {k: v for k, v in a.items() if not k.startswith(("cb_", "cr_", "sat"))} == \
        {k: v for k, v in b.items() if not k.startswith(("cb_", "cr_", "sat"))}


def test_420_repeats_chroma_rows(limits) -> None:
    f = _frame(h=48)
    cb420, cr420 = f.cb[0::2], f.cr[0::2]
    f422 = VideoFrame(index=1, y=f.y, cb=np.repeat(cb420, 2, axis=0), cr=np.repeat(cr420, 2, axis=0))
    f420 = VideoFrame(index=1, y=f.y, cb=cb420, cr=cr420, vsub=2)
    assert _measure(limits, f420) == _measure(limits, f422)
    assert {k: v.tolist() for k, v in out_of_range_masks(f420, limits).items()} == \
        {k: v.tolist() for k, v in out_of_range_masks(f422, limits).items()}


@pytest.mark.fixtures
def test_asterix_like_scan_with_arte(fixtures_dir, tmp_path) -> None:
    """A DNxHR HQ 8-bit 2048x1556 23.976 scan (like the ASTERIX file of the acceptance): measured,
    and every difference with Arte is an anomaly of format, none a refusal."""
    out = tmp_path / "o"
    result = CliRunner().invoke(app, ["analyze", str(fixtures_dir / "fmt_dnxhr_hq_2k.mov"), "--profile", str(ARTE),
                                      "--out", str(out), "--no-thumbnails"])
    assert result.exit_code == 4, result.output
    events = json.loads((out / wd.EVENTS).read_text(encoding="utf-8"))["events"]
    by_type = {e["type"]: e for e in events}
    assert by_type["format_picture"]["value_text"] == "8 bits"
    assert by_type["format_resolution"]["value_text"] == "2048x1556"
    assert by_type["format_frame_rate"]["value_text"] == "24000/1001"
    assert "format_codec" not in by_type  # DNxHR HQ is in the Arte list of §3.2.2.2 (A VERIFIER)
    probe = json.loads((out / wd.PROBE).read_text(encoding="utf-8"))
    assert (probe["video"]["bit_depth"], probe["video"]["sampling"]) == (8, "4:2:2")


@pytest.mark.fixtures
def test_prores_4444_alpha(fixtures_dir, tmp_path) -> None:
    """ProRes 4444 with alpha: decoded in 12 bits 4:4:4, the alpha plane ignored and reported."""
    out = tmp_path / "o"
    result = CliRunner().invoke(app, ["analyze", str(fixtures_dir / "fmt_prores4444_alpha.mov"), "--profile",
                                      str(CLASSIC), "--out", str(out), "--no-thumbnails"])
    assert result.exception is None or isinstance(result.exception, SystemExit), result.output
    probe = json.loads((out / wd.PROBE).read_text(encoding="utf-8"))
    assert probe["accepted"] and (probe["video"]["bit_depth"], probe["video"]["sampling"], probe["video"]["alpha"]) == (
        12, "4:4:4", True)
    events = json.loads((out / wd.EVENTS).read_text(encoding="utf-8"))["events"]
    alpha = [e for e in events if e["type"] == "alpha_channel"]
    assert [(e["severity"], e["value_text"]) for e in alpha] == [("info", "présent, ignoré par les mesures")]
    lines = (out / "measurements_video.jsonl").read_text(encoding="utf-8").splitlines()
    first = json.loads(lines[0])
    assert 64 <= first["y_p01"] <= first["y_p99"] <= 940  # testsrc2 in the legal range, as 10-bit codes
