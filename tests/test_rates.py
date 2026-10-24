"""Every frame rate is measured (Phase 6): timecodes, durations and audio follow the rate of the file."""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pad_guard import formats, workdir as wd
from pad_guard.cli import EXIT_NON_CONFORME, app
from pad_guard.rules.profile import load_profile
from pad_guard.timecode import Clock, TimecodeFormat

from conftest import PROFILES, TEST_PROFILES

pytestmark = pytest.mark.fixtures

ARTE = PROFILES / "arte_hd_sdr.yaml"
CLASSIC = TEST_PROFILES / "test_classic.yaml"


@pytest.fixture(scope="module")
def analysed(fixtures_dir, tmp_path_factory):
    cache: dict[tuple[str, Path], tuple[int, Path]] = {}

    def get(name: str, profile: Path = ARTE) -> tuple[int, Path]:
        if (name, profile) not in cache:
            out = tmp_path_factory.mktemp(name.replace(".", "_"))
            result = CliRunner().invoke(app, ["analyze", str(fixtures_dir / name), "--profile", str(profile),
                                              "--out", str(out), "--no-thumbnails"])
            assert result.exception is None or isinstance(result.exception, SystemExit), result.output
            cache[(name, profile)] = (result.exit_code, out)
        return cache[(name, profile)]

    return get


def _json(out: Path, name: str) -> dict:
    return json.loads((out / name).read_text(encoding="utf-8"))


def test_every_rate_is_measurable() -> None:
    assert set(formats.MEASURABLE_RATES) == {Fraction(24000, 1001), Fraction(24), Fraction(25), Fraction(30000, 1001),
                                             Fraction(30), Fraction(50), Fraction(60000, 1001), Fraction(60)}


def test_50p_arte_is_conforme(analysed) -> None:
    """Arte V2 prefers 50p (§3.2.2.1): a clean 50p program is CONFORME, its timecode counts to 49."""
    code, out = analysed("rate_50p.mov")
    assert code == 0 and _json(out, wd.EVENTS)["events"] == []
    m = _json(out, wd.MEASUREMENTS)
    assert m["video"]["frames"] == 1000 and m["audio"]["program"]["tc_end"] == "10:00:19:49"
    assert m["audio"]["groups"]["VO"]["integrated_lufs"] == pytest.approx(-23.0, abs=0.1)
    st = _json(out, wd.STRUCTURE)
    assert st["timecode_format"] == {"base": 50, "drop_frame": False, "frames_per_count": 1, "source": "tmcd"}


@pytest.mark.parametrize(("name", "rate", "frames", "tc_end", "drop"), [
    ("rate_2997df.mov", "30000/1001", 600, "10:00:19;29", True),
    ("rate_23976.mov", "24000/1001", 480, "10:00:19:23", False),
    ("rate_5994df.mxf", "60000/1001", 1199, "10:00:19;58", True),
])
def test_other_rates_are_analysed_with_a_format_anomaly(analysed, name, rate, frames, tc_end, drop) -> None:
    """A rate Arte does not accept is an anomaly of the report, not a refusal."""
    code, out = analysed(name)
    assert code == EXIT_NON_CONFORME
    events = _json(out, wd.EVENTS)["events"]
    fmt = [e for e in events if e["type"] == "format"]
    assert [(e["value_text"], e["threshold_text"], e["severity"]) for e in fmt] == [(rate, "25/1 ou 50/1", "blocking")]
    assert {e["type"] for e in events} <= {"format", "structure_timecode", "delivery_conversion_required"}
    m = _json(out, wd.MEASUREMENTS)
    assert m["video"]["frames"] == frames and m["integrity"]["frames_decoded"] == frames
    assert m["audio"]["program"]["tc_end"] == tc_end
    # Audio sample <-> frame mapping with a non-integer number of samples per frame (1601.6, 2002, 800.8).
    assert m["audio"]["program"]["sample_end"] == round(frames * Fraction(48000) / Fraction(rate))
    assert m["audio"]["groups"]["VO"]["integrated_lufs"] == pytest.approx(-23.0, abs=0.1)
    st = _json(out, wd.STRUCTURE)
    assert st["timecode_format"]["drop_frame"] is drop
    if drop:  # Arte asks for a non drop frame timecode at 10:00:00:00
        tc = [e["value_text"] for e in events if e["type"] == "structure_timecode"]
        assert sorted(tc) == ["10:00:00;00", "drop frame"]
    md = (out / wd.REPORT_MD).read_text(encoding="utf-8")
    assert f"images à {rate} i/s" in md and "| Format du timecode |" in md


def test_levels_durations_are_seconds_in_50p(analysed) -> None:
    """At 50p, 50 frames of white (1 s) are major and 25 frames of black (0.5 s) only minor: in frames
    (« duration_frames >= 25 ») the black would have been major too."""
    _, out = analysed("bad_levels_50p.mov")
    events = {e["type"]: e for e in _json(out, wd.EVENTS)["events"] if e["type"] in ("white_clip", "black_crush")}
    white, black = events["white_clip"], events["black_crush"]
    assert (white["frame_start"], white["frame_end"], white["tc_start"], white["tc_end"]) == (
        600, 649, "10:00:02:00", "10:00:02:49")
    assert (black["frame_start"], black["frame_end"]) == (750, 774)
    assert white["severity"] == "major" and black["severity"] == "minor"
    # The duration is a Lumiris grouping choice; the area threshold comes from Arte: no norm cap.
    assert white["severity_source"].startswith("Arte §3.2.3.3 (surface)")
    assert "NORME" not in white["severity_source"]


def test_24fps_is_analysed(analysed) -> None:
    code, out = analysed("rate24_prores.mov", CLASSIC)
    assert code == EXIT_NON_CONFORME
    fmt = [e for e in _json(out, wd.EVENTS)["events"] if e["type"] == "format" and e["title"] == "Cadence"]
    assert [(e["value_text"], e["threshold_text"]) for e in fmt] == [("24/1", "25/1")]


def test_merge_gap_and_minimums_in_seconds() -> None:
    rules = load_profile(ARTE).rules
    assert rules.merge_gap_seconds == 0.5 and rules.merge_gap_frames is None
    assert [rules.gap_frames(Fraction(r)) for r in (25, 50, Fraction(30000, 1001), Fraction(24000, 1001))] == [
        12, 25, 14, 11]
    assert [rules.min_frames("freeze", Fraction(r)) for r in (25, 50, Fraction(30000, 1001))] == [50, 100, 60]
    assert rules.min_frames("white_clip", Fraction(50)) == 1
    clock = Clock(Fraction(50), "10:00:00:00", TimecodeFormat(base=50, drop_frame=False))
    assert clock.frames_in(1.0) == 50
