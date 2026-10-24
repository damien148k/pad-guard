"""Formats: what PAD Guard measures, and the format checks against the profile (Phase 6)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from pad_guard import formats, workdir as wd
from pad_guard.cli import app
from pad_guard.probe import probe_file
from pad_guard.rules.profile import ProfileError, load_profile

from conftest import PROFILES, TEST_PROFILES

ARTE = PROFILES / "arte_hd_sdr.yaml"
CLASSIC = TEST_PROFILES / "test_classic.yaml"


def _probe(path: Path, profile: Path = ARTE):
    return probe_file(path, load_profile(profile), profile, hash_source=False)


def _checks(r) -> dict[str, tuple[str, str, str]]:
    return {c.id: (c.status, c.actual, c.type) for c in r.checks}


@pytest.mark.parametrize(("pix_fmt", "info"), [
    ("yuv422p10le", {"bit_depth": 10, "sampling": "4:2:2", "alpha": False}),
    ("yuv422p", {"bit_depth": 8, "sampling": "4:2:2", "alpha": False}),
    ("yuva444p12le", {"bit_depth": 12, "sampling": "4:4:4", "alpha": True}),
    ("gbrp10le", {"bit_depth": 10, "sampling": "rgb", "alpha": False}),
    ("yuv420p", {"bit_depth": 8, "sampling": "4:2:0", "alpha": False}),
    ("yuv411p", None), ("bayer_rggb16le", None), ("inconnu", None),
])
def test_pixel_info(pix_fmt, info) -> None:
    assert formats.pixel_info(pix_fmt) == info


@pytest.mark.fixtures
def test_mxf_op_atom(fixtures_dir) -> None:
    r = _probe(fixtures_dir / "fmt_opatom.mxf")
    assert (r.container.kind, r.container.mxf_pattern) == ("mxf", "opatom")
    assert _checks(r)["container"] == ("ok", "MXF OP-Atom", "format_container")  # Arte: mov or mxf, any pattern
    assert r.audio_streams == []


@pytest.mark.fixtures
def test_op1a_required(fixtures_dir, tmp_path) -> None:
    """A profile that asks for MXF OP1a: OP-Atom is an anomaly of the container, not a refusal."""
    raw = yaml.safe_load(ARTE.read_text(encoding="utf-8"))
    raw["format"]["containers"] = ["mxf_op1a"]
    path = tmp_path / "profiles" / "op1a.yaml"
    path.parent.mkdir()
    path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    profile = load_profile(path)
    opatom = probe_file(fixtures_dir / "fmt_opatom.mxf", profile, path, hash_source=False)
    assert opatom.accepted and _checks(opatom)["container"] == ("fail", "MXF OP-Atom", "format_container")
    op1a = probe_file(fixtures_dir / "ok_dnxhr.mxf", profile, path, hash_source=False)
    assert _checks(op1a)["container"] == ("ok", "MXF OP1a", "format_container")


@pytest.mark.fixtures
def test_h264_intra_mp4_with_arte(fixtures_dir, tmp_path) -> None:
    """H.264 High 4:2:2 Intra (what ffprobe calls XAVC Intra and AVC-Intra) is one of Arte's codecs
    (§3.2.2.2); the MP4 container is not one of the profile's: an anomaly of the report."""
    r = _probe(fixtures_dir / "fmt_h264_intra.mp4")
    assert r.accepted and r.container.kind == "mp4"
    checks = _checks(r)
    assert checks["codec"] == ("ok", "h264 High 4:2:2 Intra", "format_codec")
    assert checks["container"] == ("fail", "MP4", "format_container")
    assert checks["bit_depth"][:2] == ("ok", "10 bits") and checks["chroma"][:2] == ("ok", "4:2:2")
    codec = next(c for c in r.checks if c.id == "codec")
    assert codec.expected == "XAVC HD Intra Class 100 CBG, DNX HD 185, ProRes HQ, AVC-Intra 100, DNX HR/HQ"
    out = tmp_path / "o"
    result = CliRunner().invoke(app, ["analyze", str(fixtures_dir / "fmt_h264_intra.mp4"), "--profile", str(ARTE),
                                      "--out", str(out), "--no-thumbnails"])
    assert result.exit_code == 4, result.output
    events = json.loads((out / wd.EVENTS).read_text(encoding="utf-8"))["events"]
    assert [(e["type"], e["severity"], e["value_text"]) for e in events] == [("format_container", "blocking", "MP4")]
    m = json.loads((out / wd.MEASUREMENTS).read_text(encoding="utf-8"))
    assert m["integrity"]["frames_decoded"] == 500 and m["integrity"]["errors"] == []


def test_profile_picture_forms(tmp_path) -> None:
    raw = yaml.safe_load(CLASSIC.read_text(encoding="utf-8"))
    raw["format"]["pix_fmt"] = "yuv422p10le"  # both forms
    path = tmp_path / "both.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    with pytest.raises(ProfileError, match="pas les deux"):
        load_profile(path)
    del raw["format"]["bit_depth_allowed"], raw["format"]["chroma_allowed"]  # older form alone: accepted
    path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    assert load_profile(path).format.pix_fmt == "yuv422p10le"
