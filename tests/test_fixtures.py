"""Checks that make_fixtures.sh produced what the roadmap describes (measured with FFmpeg itself)."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.fixtures


def ffprobe(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-count_packets", "-show_format", "-show_streams", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(out)


def loudness(path: Path, channels: list[int], start: float = 0.0, duration: float | None = None) -> tuple[float, float]:
    """Integrated loudness (LUFS) and true peak (dBTP) of the given global channel indices (0-based)."""
    pans = "|".join(f"c{i}=c{ch}" for i, ch in enumerate(channels))
    layout = "stereo" if len(channels) == 2 else "mono"
    cmd = ["ffmpeg", "-nostats", "-hide_banner", "-ss", str(start)]
    if duration is not None:
        cmd += ["-t", str(duration)]
    cmd += [
        "-i", str(path),
        "-filter_complex", f"amerge=inputs={_audio_streams(path)},pan={layout}|{pans},ebur128=peak=true",
        "-f", "null", "-",
    ]
    err = subprocess.run(cmd, check=True, capture_output=True, text=True).stderr
    summary = err[err.rindex("Summary:"):]
    i = float(re.search(r"I:\s+(-?[\d.]+|-inf) LUFS", summary).group(1))
    tp = float(re.search(r"Peak:\s+(-?[\d.]+|-inf) dBFS", summary).group(1))
    return i, tp


def _audio_streams(path: Path) -> int:
    return sum(s["codec_type"] == "audio" for s in ffprobe(path)["streams"])


def signalstats(path: Path, frame: int) -> dict[str, float]:
    """FFmpeg signalstats of one frame: YMIN, YMAX (10-bit code values), BRNG (fraction out of range)..."""
    err = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-map", "0:v:0",
            "-vf", f"select=eq(n\\,{frame}),signalstats=stat=brng,metadata=print", "-f", "null", "-",
        ],
        check=True, capture_output=True, text=True,
    ).stderr
    return {k: float(v) for k, v in re.findall(r"lavfi\.signalstats\.(\w+)=([-\d.e]+)", err)}


def luma_range(path: Path, frame: int) -> tuple[int, int]:
    stats = signalstats(path, frame)
    return int(stats["YMIN"]), int(stats["YMAX"])


def video(info: dict) -> dict:
    return next(s for s in info["streams"] if s["codec_type"] == "video")


def tc(info: dict) -> str | None:
    for s in info["streams"]:
        if "timecode" in s.get("tags", {}):
            return s["tags"]["timecode"]
    return info["format"].get("tags", {}).get("timecode")


@pytest.mark.parametrize(
    ("name", "codec", "profile", "frames", "start_tc", "audio_layout"),
    [
        ("ok_prores.mov", "prores", "HQ", 500, "09:59:50:00", [2]),
        ("ok_dnxhr.mxf", "dnxhd", "DNXHR HQX", 500, "09:59:50:00", [2]),
        ("bad_levels.mov", "prores", "HQ", 500, "09:59:50:00", [2]),
        ("bad_audio.mov", "prores", "HQ", 500, "09:59:50:00", [2]),
        ("bad_structure.mov", "prores", "HQ", 500, "00:00:00:00", [2]),
        ("wrong_codec.mov", "prores", "LT", 500, "09:59:50:00", [2]),
        ("arte_ok.mov", "prores", "HQ", 500, "10:00:00:00", [1] * 6),
        ("arte_bad.mov", "prores", "HQ", 625, "10:00:00:00", [1] * 6),
    ],
)
def test_fixture_metadata(fixtures_dir, name, codec, profile, frames, start_tc, audio_layout) -> None:
    info = ffprobe(fixtures_dir / name)
    v = video(info)
    assert (v["codec_name"], v["profile"]) == (codec, profile)
    assert v["pix_fmt"] == "yuv422p10le"
    assert (v["width"], v["height"]) == (1920, 1080)
    assert v["r_frame_rate"] == v["avg_frame_rate"] == "25/1"
    assert v["field_order"] == "progressive"
    assert v["color_range"] == "tv"
    assert v["color_primaries"] == v["color_transfer"] == v["color_space"] == "bt709"
    assert int(v["nb_read_packets"]) == frames
    assert tc(info) == start_tc
    audio = [s for s in info["streams"] if s["codec_type"] == "audio"]
    assert [s["channels"] for s in audio] == audio_layout
    assert all(s["codec_name"] == "pcm_s24le" and s["sample_rate"] == "48000" for s in audio)


@pytest.mark.parametrize("name", ["ok_prores.mov", "ok_dnxhr.mxf", "bad_structure.mov"])
def test_program_loudness_ok(fixtures_dir, name) -> None:
    i, tp = loudness(fixtures_dir / name, [0, 1], start=10)
    assert i == pytest.approx(-23.0, abs=0.2)
    assert tp < -3.0


def test_bad_audio_loudness(fixtures_dir) -> None:
    i, tp = loudness(fixtures_dir / "bad_audio.mov", [0, 1], start=10)
    assert -16.5 <= i <= -15.5
    assert tp > -1.0


def test_classic_head(fixtures_dir) -> None:
    # 1 kHz at -18 dBFS during the bars, silence during the black.
    path = fixtures_dir / "ok_prores.mov"
    _, tone_peak = loudness(path, [0, 1], start=0, duration=5)
    assert tone_peak == pytest.approx(-18.0, abs=0.2)
    assert luma_range(path, 300 - 50) != (64, 64)  # program
    assert luma_range(path, 200) == (64, 64)  # black, exactly 0 %


@pytest.mark.parametrize("pair", [[0, 1], [2, 3], [4, 5]])
def test_arte_ok_pairs(fixtures_dir, pair) -> None:
    i, tp = loudness(fixtures_dir / "arte_ok.mov", pair)
    assert i == pytest.approx(-23.0, abs=0.2)
    assert tp < -1.0


def test_arte_bad_audio(fixtures_dir) -> None:
    path = fixtures_dir / "arte_bad.mov"
    _, tp = loudness(path, [2, 3])
    assert tp == float("-inf")  # pair 2 digitally silent for the whole file
    _, tp = loudness(path, [0, 1])
    assert tp > -1.0


def test_bad_levels(fixtures_dir) -> None:
    path = fixtures_dir / "bad_levels.mov"
    # Around the defects, testsrc2 is legal except for ~0.04 % of edge pixels (ProRes ringing).
    for frame in (299, 325, 374, 400):
        assert signalstats(path, frame)["BRNG"] < 0.01
    assert luma_range(path, 300) == (975, 975)
    assert luma_range(path, 324) == (975, 975)
    assert luma_range(path, 375) == (40, 40)
    assert luma_range(path, 399) == (40, 40)
