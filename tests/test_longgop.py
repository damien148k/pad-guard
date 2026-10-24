"""Long-GOP codecs and containers (Phase 6): XDCAM HD422, H.264 and HEVC, MXF OP-Atom."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from pad_guard import workdir as wd
from pad_guard.cli import app
from pad_guard.decode.video import VideoDecoder, read_frames

from conftest import PROFILES, TEST_PROFILES

pytestmark = pytest.mark.fixtures

ARTE = PROFILES / "arte_hd_sdr.yaml"
CLASSIC = TEST_PROFILES / "test_classic.yaml"


def _analyse(path: Path, out: Path, profile: Path = ARTE) -> tuple[list[dict], dict]:
    result = CliRunner().invoke(app, ["analyze", str(path), "--profile", str(profile), "--out", str(out),
                                      "--no-thumbnails"])
    assert result.exception is None or isinstance(result.exception, SystemExit), result.output
    events = json.loads((out / wd.EVENTS).read_text(encoding="utf-8"))["events"]
    return events, json.loads((out / wd.MEASUREMENTS).read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", ["xdcam_hd422.mxf", "h264_lgop.mp4", "hevc_lgop.mp4"])
def test_random_access_is_exact(fixtures_dir, name) -> None:
    """A seek lands on a key frame and decodes forward: the frame read is the frame decoded in sequence."""
    path = fixtures_dir / name
    frames = [f.y.copy() for f in VideoDecoder(path).frames()]
    wanted = [0, 5, 13, 26, 50, 77, len(frames) - 1]
    got = {f.index: f.y for f in read_frames(path, wanted)}
    assert sorted(got) == sorted(set(wanted)) and all(np.array_equal(frames[i], got[i]) for i in wanted)


def test_xdcam_hd422(fixtures_dir, tmp_path) -> None:
    events, m = _analyse(fixtures_dir / "xdcam_hd422.mxf", tmp_path / "o")
    assert m["integrity"]["frames_decoded"] == 100 and m["integrity"]["errors"] == []
    assert m["integrity"]["keyframes"] == list(range(0, 100, 12))  # GOP 12
    # Progressive testsrc2 coded as fields: the pictures say progressive, the flag tt.
    assert m["scan"]["detected"] == "progressive" and m["video"]["first_field"] == "top"
    types = {e["type"]: e for e in events}
    assert types["format_codec"]["value_text"] == "mpeg2video 4:2:2"
    assert types["format_picture"]["value_text"] == "8 bits" and "integrity" not in types


def test_long_gop_error_spoils_the_gop(fixtures_dir, tmp_path) -> None:
    """A damaged packet in an H.264 GOP: the event runs to the frame before the next key frame."""
    data = bytearray((fixtures_dir / "h264_lgop.mp4").read_bytes())
    for k in range(int(len(data) * 0.40), int(len(data) * 0.50), 501):  # video and audio are interleaved
        data[k] ^= 0x5A
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(bytes(data))
    events, m = _analyse(bad, tmp_path / "o", CLASSIC)
    keys = m["integrity"]["keyframes"]
    assert keys == [0, 25, 50, 75]
    errors = [e for e in events if e["type"] == "integrity" and e["title"].startswith("Erreur de décodage")]
    assert errors
    for e in errors:
        nxt = next(k for k in keys if k > e["frame_start"])
        assert e["frame_end"] == nxt - 1 and "GOP long" in e["detail"]


def test_op_atom_audio_reported_not_missing(fixtures_dir, tmp_path) -> None:
    """MXF OP-Atom: the audio is in other files. Information, not a missing VO pair."""
    events, _ = _analyse(fixtures_dir / "fmt_opatom.mxf", tmp_path / "o")
    audio = [e for e in events if e["type"] == "audio_not_analysed"]
    assert [e["severity"] for e in audio] == ["info"]
    assert not any(e["type"].startswith("format") and "pistes absentes" in e["value_text"] for e in events)
