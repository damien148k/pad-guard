"""Interlaced files measured field by field (PSE), PsF (Phase 6)."""

from __future__ import annotations

import json

import numpy as np
import pytest
import yaml
from typer.testing import CliRunner

from pad_guard import workdir as wd
from pad_guard.cli import app
from pad_guard.measure.video import FrameMeter, VideoLimits, _bob, first_field
from pad_guard.decode.video import VideoFrame
from pad_guard.rules.profile import load_profile

from conftest import PROFILES

ARTE = PROFILES / "arte_hd_sdr.yaml"


def test_first_field_of_the_flag() -> None:
    assert [first_field(f) for f in ("tt", "tb", "bb", "bt", "progressive", None)] == [
        "top", "top", "bottom", "bottom", None, None]


def test_bob_interpolation() -> None:
    field = np.array([[0], [100], [200]], np.uint16)
    assert _bob(field, onto_bottom=True, rows=3)[:, 0].tolist() == [50, 150, 200]
    assert _bob(field, onto_bottom=False, rows=3)[:, 0].tolist() == [0, 50, 150]


def test_field_flash_invisible_on_whole_frames() -> None:
    """Bright top field, dark bottom field, every frame the same: no frame change, two field changes."""
    limits = VideoLimits.from_profile(load_profile(ARTE))
    y = np.empty((32, 16), np.uint16)
    y[0::2], y[1::2] = 800, 100
    chroma = np.full((32, 8), 512, np.uint16)
    meter = FrameMeter(limits, strip_rows=16)
    m = meter.measure(VideoFrame(index=1, y=y, cb=chroma, cr=chroma), y, "top")
    assert m["d_up_pct"] == 0.0 and m["d_down_pct"] == 0.0
    assert (m["fu1"], m["fd1"], m["fu2"], m["fd2"]) == (100.0, 0.0, 0.0, 100.0)
    assert set(meter.measure(VideoFrame(index=1, y=y, cb=chroma, cr=chroma), y)) >= {"d_mean"}
    assert "fu1" not in meter.measure(VideoFrame(index=1, y=y, cb=chroma, cr=chroma), y)


def _analyse(fixtures_dir, tmp_path, name: str, profile=ARTE):
    out = tmp_path / name.replace(".", "_")
    result = CliRunner().invoke(app, ["analyze", str(fixtures_dir / name), "--profile", str(profile),
                                      "--out", str(out), "--no-thumbnails"])
    assert result.exception is None or isinstance(result.exception, SystemExit), result.output
    return out, json.loads((out / wd.EVENTS).read_text(encoding="utf-8"))["events"]


@pytest.mark.fixtures
def test_interlaced_flash_found_field_by_field(fixtures_dir, tmp_path) -> None:
    out, events = _analyse(fixtures_dir, tmp_path, "interlaced_flash.mov")
    pse = [e for e in events if e["type"] == "pse"]
    assert [(e["frame_start"], e["frame_end"], e["value_text"]) for e in pse] == [(0, 99, "25 flashs/s")]
    m = json.loads((out / wd.MEASUREMENTS).read_text(encoding="utf-8"))
    assert m["scan"]["detected"] == "interlaced" and m["video"]["first_field"] == "top"
    frames = [json.loads(line) for line in (out / "measurements_video.jsonl").read_text(encoding="utf-8").splitlines()]
    assert max(f["d_up_pct"] or 0 for f in frames) < 25  # nothing visible on whole frames
    md = (out / wd.REPORT_MD).read_text(encoding="utf-8")
    assert "PSE analysé trame par trame" in md


@pytest.mark.fixtures
def test_psf_profile_accepts_progressive_fields(fixtures_dir, tmp_path) -> None:
    """Progressive pictures flagged interlaced: a label error for Arte (progressive), right for a PsF profile."""
    _, arte = _analyse(fixtures_dir, tmp_path, "psf_prores.mov")
    assert {e["type"] for e in arte} >= {"scan_flag_mismatch"}
    raw = yaml.safe_load(ARTE.read_text(encoding="utf-8"))
    raw["format"]["field_order"] = "psf"
    profile = tmp_path / "profiles" / "psf.yaml"
    profile.parent.mkdir()
    profile.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    import shutil
    shutil.copytree(PROFILES.parent / "normes", tmp_path / "normes", ignore=shutil.ignore_patterns("sources"))
    _, psf = _analyse(fixtures_dir, tmp_path, "psf_prores.mov", profile)
    assert not {e["type"] for e in psf} & {"scan_flag_mismatch", "scan_interlaced", "format"}
