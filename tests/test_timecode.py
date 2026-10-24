"""Timecode: drop frame, bases above 30, frame pairs, and the format read in MOV and MXF files."""

from __future__ import annotations

import re
import shutil
import struct
from fractions import Fraction
from pathlib import Path

import pytest

from pad_guard import timecode
from pad_guard.probe import probe_file
from pad_guard.probe import tc_reader
from pad_guard.rules.profile import load_profile
from pad_guard.timecode import Clock, TimecodeFormat

from conftest import TEST_PROFILES

CLASSIC = TEST_PROFILES / "test_classic.yaml"
DF30 = TimecodeFormat(base=30, drop_frame=True)
DF60 = TimecodeFormat(base=60, drop_frame=True)


@pytest.mark.parametrize(("tc", "fmt", "count"), [
    # Counters written by FFmpeg 9 in the tmcd sample / MXF start timecode of the fixtures.
    ("10:00:59;28", DF30, 1_080_718),
    ("10:00:59;58", DF60, 2_161_438),
    ("10:00:00:30", TimecodeFormat(base=50, drop_frame=False), 1_800_030),
    ("10:00:00:23", TimecodeFormat(base=24, drop_frame=False), 864_023),
    ("00:01:00;02", DF30, 1800),  # first number of minute 1: 00 and 01 are skipped
    ("00:10:00;00", DF30, 17_982),  # minute 10 keeps its numbers
])
def test_counts(tc, fmt, count) -> None:
    assert timecode.to_count(tc, fmt) == count
    assert timecode.from_count(count, fmt) == tc


@pytest.mark.parametrize("fmt", [DF30, DF60, TimecodeFormat(base=50, drop_frame=False),
                                 TimecodeFormat(base=24, drop_frame=False)])
def test_roundtrip_over_a_day(fmt) -> None:
    sep = ";" if fmt.drop_frame else ":"
    per_day = timecode.to_count(f"23:59:59{sep}{fmt.base - 1:02d}", fmt) + 1
    assert per_day == (144 * (fmt.base * 600 - 9 * fmt.base // 15) if fmt.drop_frame else 86400 * fmt.base)
    for n in range(0, per_day, 997):
        text = timecode.from_count(n, fmt)
        assert timecode.is_valid(text, fmt) and timecode.to_count(text, fmt) == n


def test_skipped_drop_frame_numbers_are_invalid() -> None:
    assert not timecode.is_valid("10:01:00;00", DF30) and not timecode.is_valid("10:01:00;01", DF30)
    assert timecode.is_valid("10:01:00;02", DF30) and timecode.is_valid("10:10:00;00", DF30)
    assert not timecode.is_valid("10:01:00;03", DF60) and timecode.is_valid("10:01:00;04", DF60)
    with pytest.raises(ValueError):
        timecode.to_count("10:00:00;00", TimecodeFormat(base=25, drop_frame=False))


def test_clock_50p_base_50_shows_frames_up_to_49() -> None:
    clock = Clock(Fraction(50), "10:00:00:30", TimecodeFormat(base=50, drop_frame=False))
    assert [clock.tc(i) for i in (0, 19, 20)] == ["10:00:00:30", "10:00:00:49", "10:00:01:00"]
    assert clock.frame("10:00:01:00") == 20 and clock.seconds(50) == 1.0


def test_clock_frame_pairs() -> None:
    """50p with a base 25 timecode: the two frames of a pair share the timecode, with a suffix."""
    clock = Clock(Fraction(50), "10:00:00:15", TimecodeFormat(base=25, drop_frame=False, frames_per_count=2))
    a, b = timecode.PAIR_SUFFIX
    assert [clock.tc(i) for i in range(4)] == [f"10:00:00:15{a}", f"10:00:00:15{b}", f"10:00:00:16{a}", f"10:00:00:16{b}"]
    assert clock.frame(f"10:00:00:16{b}") == 3 and clock.frame("10:00:00:16") == 2
    assert clock.duration(51) == "00:00:01:00 + 1 image"


def test_clock_23976_seconds_use_the_rate() -> None:
    clock = Clock(Fraction(24000, 1001), "00:00:00:00")
    assert clock.format.base == 24 and clock.tc(24) == "00:00:01:00"
    assert clock.seconds(24) == pytest.approx(1.001)


def test_clock_drop_frame_from_the_text() -> None:
    clock = Clock(Fraction(30000, 1001), "10:00:59;28")
    assert clock.format.drop_frame and clock.tc(2) == "10:01:00;02"


@pytest.mark.parametrize(("name", "base", "drop", "source"), [
    ("tc_50p.mov", 50, False, "tmcd"), ("tc_50p.mxf", 50, False, "mxf"), ("tc_5994df.mov", 60, True, "tmcd"),
    ("tc_2997df.mxf", 30, True, "mxf"), ("tc_23976.mov", 24, False, "tmcd"), ("ok_prores.mov", 25, False, "tmcd"),
    ("ok_dnxhr.mxf", 25, False, "mxf"),
])
def test_format_read_in_the_file(fixtures_dir, name, base, drop, source) -> None:
    r = probe_file(fixtures_dir / name, load_profile(CLASSIC), CLASSIC, hash_source=False)
    assert r.timecode_format == TimecodeFormat(base=base, drop_frame=drop, frames_per_count=1, source=source)


def _patch_mov_base25(src: Path, dst: Path) -> None:
    """tc_50p.mov with its tmcd track rewritten in base 25 (one timecode frame per two frames), as
    some tools write it: ffprobe then prints 10:00:00:15, exactly like a 25p file."""
    data = bytearray(src.read_bytes())
    for m in re.finditer(rb"stsd", data):
        entry = m.start() + 12  # box type, version and flags, entry count
        if data[entry + 4:entry + 8] == b"tmcd":
            scale, duration, frames = struct.unpack(">IIB", data[entry + 24:entry + 33])
            assert frames == 50
            data[entry + 28:entry + 33] = struct.pack(">IB", duration * 2, 25)
    at = data.find(struct.pack(">I", 1_800_030))
    data[at:at + 4] = struct.pack(">I", 900_015)
    dst.write_bytes(bytes(data))


def _patch_mxf_base25(src: Path, dst: Path) -> None:
    data = bytearray(src.read_bytes())
    for m in re.finditer(rb"\x15\x02\x00\x02\x00\x32", data):  # rounded timecode base 50
        data[m.start() + 4:m.start() + 6] = struct.pack(">H", 25)
    for m in re.finditer(rb"\x15\x01\x00\x08", data):  # start timecode
        data[m.start() + 4:m.start() + 12] = struct.pack(">q", 900_015)
    dst.write_bytes(bytes(data))


@pytest.mark.parametrize(("name", "patch"), [("tc_50p.mov", _patch_mov_base25), ("tc_50p.mxf", _patch_mxf_base25)])
def test_50p_with_a_base_25_timecode(fixtures_dir, tmp_path, name, patch) -> None:
    path = tmp_path / name
    patch(fixtures_dir / name, path)
    r = probe_file(path, load_profile(CLASSIC), CLASSIC, hash_source=False)
    assert r.timecode == "10:00:00:15"  # what ffprobe prints: the base is not in its output
    fmt = r.timecode_format
    assert (fmt.base, fmt.frames_per_count) == (25, 2)
    clock = Clock(Fraction(50), r.timecode, fmt)
    assert clock.tc(1).startswith("10:00:00:15") and clock.tc(2).startswith("10:00:00:16")


def test_unreadable_file_gives_no_format(tmp_path) -> None:
    junk = tmp_path / "x.mov"
    junk.write_bytes(b"\x00\x00\x00\x08junk" * 4)
    assert tc_reader.read_format(junk, "mov", Fraction(25), "10:00:00:00") is None
    shutil.copyfile(junk, tmp_path / "x.mxf")
    assert tc_reader.read_format(tmp_path / "x.mxf", "mxf", Fraction(25), "10:00:00:00") is None
