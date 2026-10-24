from __future__ import annotations

import json
import math
import subprocess
from pathlib import Path

import numpy as np
import pytest

from pad_guard import measure
from pad_guard.decode.video import VideoFrame
from pad_guard.measure import audio as am
from pad_guard.measure.video import FrameMeter, VideoLimits, hfilter, measure_frames, pct_to_code
from pad_guard.probe import probe_file
from pad_guard.probe.models import AudioTrack
from pad_guard.rules.profile import load_profile

from conftest import PROFILES, TEST_PROFILES
from test_fixtures import loudness

CLASSIC = TEST_PROFILES / "test_classic.yaml"
ARTE = PROFILES / "arte_hd_sdr.yaml"


def run(fixture: Path, profile_path: Path, out: Path, workers: int | None = None):
    profile = load_profile(profile_path)
    return measure.run(probe_file(fixture, profile, profile_path), profile, out, workers)


def video_lines(out: Path) -> list[dict]:
    with (out / measure.VIDEO_FILE).open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


def audio_lines(out: Path, group: str) -> list[dict]:
    with (out / measure.AUDIO_FILE).open(encoding="utf-8") as f:
        return [rec for rec in map(json.loads, f) if rec["g"] == group]


@pytest.fixture(scope="module")
def measured(fixtures_dir, tmp_path_factory):
    """Measure each fixture once for the module: name -> (Measurements, output dir)."""
    cache: dict[str, tuple] = {}

    def get(name: str, profile_path: Path = CLASSIC):
        key = f"{name}:{profile_path.name}"
        if key not in cache:
            out = tmp_path_factory.mktemp(name.replace(".", "_"))
            cache[key] = (run(fixtures_dir / name, profile_path, out), out)
        return cache[key]

    return get


# --- unit: thresholds, prefilter, frame meter -------------------------------------------------


def test_pct_to_code_rounded_outward() -> None:
    legal = (64, 940)
    assert pct_to_code(-1.0, legal, "low") == 55  # 55.24
    assert pct_to_code(103.0, legal, "high") == 967  # 966.28
    assert pct_to_code(-5.0, legal, "low") == 20  # 20.2
    assert pct_to_code(105.0, legal, "high") == 984  # 983.8
    assert pct_to_code(0.0, legal, "low") == 64 and pct_to_code(100.0, legal, "high") == 940


def test_limits_from_profile() -> None:
    lim = VideoLimits.from_profile(load_profile(ARTE))
    assert (lim.y_legal, lim.y_tolerance, lim.rgb, lim.prefilter_taps) == ((64, 940), (55, 967), (20, 984), 3)


@pytest.mark.parametrize("taps", [3, 5])
def test_hfilter_matches_convolution(taps: int) -> None:
    rng = np.random.default_rng(1)
    plane = rng.integers(0, 1024, size=(4, 37), dtype=np.uint16)
    kernel = {3: [1, 2, 1], 5: [1, 4, 6, 4, 1]}[taps]
    half = taps // 2
    padded = np.pad(plane.astype(np.int64), ((0, 0), (half, half)), mode="edge")
    expected = np.stack([np.convolve(row, kernel, mode="valid") for row in padded])
    expected = (expected + sum(kernel) // 2) // sum(kernel)
    assert np.array_equal(hfilter(plane, taps), expected)


def _frame(y, cb, cr, index: int = 0) -> VideoFrame:
    return VideoFrame(index=index, y=np.asarray(y, np.uint16), cb=np.asarray(cb, np.uint16), cr=np.asarray(cr, np.uint16))


def _flat(h: int, w: int, y: int, cb: int = 512, cr: int = 512) -> VideoFrame:
    return _frame(np.full((h, w), y), np.full((h, w // 2), cb), np.full((h, w // 2), cr))


def _limits(prefilter: int | None = None) -> VideoLimits:
    return VideoLimits(y_legal=(64, 940), y_tolerance=(55, 967), rgb=(20, 984), prefilter_taps=prefilter, matrix="bt709",
                       flash_delta_pct=10.0)


@pytest.mark.parametrize(
    ("y", "below", "above", "below_legal", "above_legal", "rgb_out"),
    [
        (64, 0, 0, 0, 0, 0),
        (63, 0, 0, 100, 0, 0),
        (55, 0, 0, 100, 0, 0),  # tolerated bound, inclusive
        (54, 100, 0, 100, 0, 0),
        (20, 100, 0, 100, 0, 0),  # RGB bound, inclusive
        (19, 100, 0, 100, 0, 100),
        (967, 0, 0, 0, 100, 0),
        (968, 0, 100, 0, 100, 0),
        (984, 0, 100, 0, 100, 0),
        (985, 0, 100, 0, 100, 100),
    ],
)
def test_bounds_are_inclusive(y, below, above, below_legal, above_legal, rgb_out) -> None:
    r = FrameMeter(_limits()).measure(_flat(8, 16, y))
    assert (r["y_below_pct"], r["y_above_pct"]) == (below, above)
    assert (r["y_below_legal_pct"], r["y_above_legal_pct"]) == (below_legal, above_legal)
    assert r["rgb_out_pct"] == rgb_out
    assert r["y_min"] == r["y_max"] == r["y_p01"] == r["y_p99"] == y


def test_percentiles_nearest_rank() -> None:
    # 1000 rows x 2 columns: values 0..999 twice. 0.1 % of 2000 = 2 pixels -> value 0; 99.9 % -> 998.
    col = np.repeat(np.arange(1000), 1).reshape(1000, 1)
    y = np.hstack([col, col])
    r = FrameMeter(_limits()).measure(_frame(y, np.full((1000, 1), 512), np.full((1000, 1), 512)))
    assert (r["y_min"], r["y_p01"], r["y_p99"], r["y_max"]) == (0, 0, 998, 999)
    assert r["y_mean"] == 499.5


def test_saturated_red_is_out_of_gamut() -> None:
    # Cr at the top of the legal range with mid grey: R = Y + 1.5748 * 876/896 * 448 > 105 %.
    r = FrameMeter(_limits()).measure(_flat(4, 8, 502, cb=512, cr=960))
    assert r["rgb_out_pct"] == 100
    assert (r["cr_min"], r["cr_max"]) == (960, 960)
    assert r["sat_max"] == 448


def _rgb_reference(y: np.ndarray, cb: np.ndarray, cr: np.ndarray) -> int:
    """Float64, pixel by pixel, written independently of the vectorised meter."""
    kr, kb = 0.2126, 0.0722
    kg = 1 - kr - kb
    h, w = y.shape
    count = 0
    for i in range(h):
        for j in range(w):
            k = j // 2
            if j % 2 == 0 or k + 1 >= cb.shape[1]:
                c_b, c_r = cb[i, k], cr[i, k]
            else:
                c_b, c_r = (cb[i, k] + cb[i, k + 1]) / 2, (cr[i, k] + cr[i, k + 1]) / 2
            yn = (y[i, j] - 64) / 876
            pb, pr = (c_b - 512) / 896, (c_r - 512) / 896
            rgb = (yn + 2 * (1 - kr) * pr, yn - 2 * kb * (1 - kb) / kg * pb - 2 * kr * (1 - kr) / kg * pr,
                   yn + 2 * (1 - kb) * pb)
            codes = [64 + 876 * v for v in rgb]
            count += any(c < 20 or c > 984 for c in codes)
    return count


def test_rgb_gamut_matches_reference() -> None:
    rng = np.random.default_rng(7)
    y = rng.integers(64, 941, size=(20, 64)).astype(np.uint16)
    cb = rng.integers(200, 825, size=(20, 32)).astype(np.uint16)
    cr = rng.integers(200, 825, size=(20, 32)).astype(np.uint16)
    expected = _rgb_reference(y.astype(float), cb.astype(float), cr.astype(float))
    assert 0 < expected < y.size  # the frame mixes legal and illegal pixels
    r = FrameMeter(_limits(), strip_rows=6).measure(_frame(y, cb, cr))  # strips that do not divide 20
    assert r["rgb_out_pct"] == round(100 * expected / y.size, 4)


def test_strips_do_not_change_results() -> None:
    rng = np.random.default_rng(3)
    frame = _frame(rng.integers(0, 1024, (45, 64)), rng.integers(0, 1024, (45, 32)), rng.integers(0, 1024, (45, 32)))
    results = {json.dumps(FrameMeter(_limits(3), strip_rows=rows).measure(frame)) for rows in (1, 7, 16, 45, 64)}
    assert len(results) == 1


def _luminance_reference(code: int) -> float:
    return min(max((code - 64) / 876, 0.0), 1.0) ** 2.4


def test_frame_differences_match_reference() -> None:
    rng = np.random.default_rng(11)
    prev = rng.integers(0, 1024, (24, 40))
    cur = rng.integers(0, 1024, (24, 40))
    meter = FrameMeter(_limits(3), strip_rows=7)
    chroma = np.full((24, 20), 512)
    r = meter.measure(_frame(cur, chroma, chroma, 1), np.asarray(prev, np.uint16))
    lum_prev = np.vectorize(_luminance_reference)(prev)
    lum_cur = np.vectorize(_luminance_reference)(cur)
    assert r["d_mean"] == round(float(np.abs(cur - prev).mean()), 3)  # unfiltered, despite the prefilter
    assert r["d_up_pct"] == round(100 * float((lum_cur - lum_prev > 0.1).mean()), 4)
    assert r["d_down_pct"] == round(100 * float((lum_prev - lum_cur > 0.1).mean()), 4)
    first = meter.measure(_frame(cur, chroma, chroma, 0))
    assert first["d_mean"] is first["d_up_pct"] is first["d_down_pct"] is None


def test_flash_table_bounds() -> None:
    up = _limits().flash_table().astype(int)
    lum = _limits().luminance()
    for p in (0, 64, 300, 700, 900):
        assert lum[up[p]] - lum[p] > 0.1 and lum[up[p] - 1] - lum[p] <= 0.1
    assert up[940] == up[1023] == 1024  # white cannot rise


def test_parallel_matches_sequential() -> None:
    rng = np.random.default_rng(5)
    frames = [
        _frame(rng.integers(0, 1024, (36, 48)), rng.integers(0, 1024, (36, 24)), rng.integers(0, 1024, (36, 24)), i)
        for i in range(9)
    ]
    sequential = list(measure_frames(frames, _limits(3), workers=1))
    parallel = list(measure_frames(frames, _limits(3), workers=2))  # 4 slots for 9 frames: slots are reused
    assert [r["f"] for r in parallel] == list(range(9))
    assert parallel == sequential
    assert sequential[0]["d_mean"] is None and all(r["d_mean"] > 0 for r in sequential[1:])


# --- unit: audio ------------------------------------------------------------------------------


def test_clip_runs_across_blocks_and_chunks() -> None:
    edges = np.array([0, 4, 8])
    carry = np.zeros(1, dtype=np.int64)
    # chunk 1: run of 3 inside block 0, run of 2 open at the end of the chunk (block 2)
    clip, carry, ended = am._clip_runs(np.array([[0, 1, 1, 1, 0, 0, 0, 0, 0, 0, 1, 1]], bool), edges, carry)
    assert clip.tolist() == [[3, 0, 0]] and carry.tolist() == [2] and ended.tolist() == [0]
    # chunk 2: the open run continues for 5 samples and ends in block 1 -> counted whole (7)
    clip, carry, ended = am._clip_runs(np.array([[1, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0]], bool), edges, carry)
    assert clip.tolist() == [[0, 7, 0]] and carry.tolist() == [0]
    # a run open at a chunk end that stops exactly there is reported as "ended" for the previous block
    _, carry, _ = am._clip_runs(np.array([[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1]], bool), edges, carry)
    clip, carry, ended = am._clip_runs(np.zeros((1, 12), bool), edges, carry)
    assert clip.tolist() == [[0, 0, 0]] and ended.tolist() == [1] and carry.tolist() == [0]


def _wav(tmp_path: Path, expr: str, seconds: float = 1.0) -> Path:
    path = tmp_path / "tone.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"aevalsrc='{expr}':s=48000:d={seconds}",
         "-c:a", "pcm_s24le", str(path)],
        check=True,
    )
    return path


def _levels(path: Path, program: tuple[int, int] = (0, 48000)) -> am.LevelPass:
    levels = am.LevelPass(path=path, tracks=[AudioTrack(track=1, stream_index=0, channel=0)], bit_depths=[24],
                          pairs=[], block=4800, program=program)
    levels.run()
    return levels


def test_true_peak_inter_sample(tmp_path) -> None:
    # fs/4 sine at 45 degrees: every sample at 0.5 * 0.707 (-9.03 dBFS), true peak 0.5 (-6.02 dBTP).
    levels = _levels(_wav(tmp_path, "0.5*sin(2*PI*12000*t+PI/4)"))
    (track,) = am.track_levels(levels)
    assert track.peak_dbfs == pytest.approx(-9.03, abs=0.01)
    assert track.true_peak_dbtp == pytest.approx(-6.02, abs=0.1)
    assert track.rms_dbfs == pytest.approx(-9.03, abs=0.01)


def test_full_scale_runs(tmp_path) -> None:
    # 1 s of silence with 0.25 s at full scale from t = 0.5 s: one run of 12000 samples, in block 7.
    levels = _levels(_wav(tmp_path, "between(t,0.5,0.75-1/96000)"))
    assert am.track_levels(levels)[0].full_scale_samples == 12000
    clip = levels.blocks["clip"][0]
    assert clip.tolist() == [0] * 7 + [12000] + [0] * 2


def test_program_totals_are_sample_exact(tmp_path) -> None:
    # Loud first half, silent second half: a programme range on the second half has no sample.
    path = _wav(tmp_path, "0.5*sin(2*PI*1000*t)*lt(t,0.5)")
    (track,) = am.track_levels(_levels(path, program=(24000, 48000)))
    assert track.peak_dbfs is None and track.rms_dbfs is None
    # The reconstructed signal rings for a few samples after the cut (inter-sample values only).
    assert track.true_peak_dbtp < -20
    (track,) = am.track_levels(_levels(path, program=(24000 + 48, 48000)))  # 1 ms after the cut
    assert track.true_peak_dbtp is None


def test_true_peak_credited_to_its_sample(tmp_path) -> None:
    # One sample at 0.5 on the last sample of block 5 (index 28799). Its inter-sample peak belongs
    # to block 5; block 6 only gets the small ringing of the interpolation filter.
    levels = _levels(_wav(tmp_path, "0.5*eq(n,28799)"))
    tp = levels.blocks["tp"][0]
    assert 20 * np.log10(tp[5]) == pytest.approx(-6.02, abs=0.1)
    assert 0 < tp[6] and 20 * np.log10(tp[6]) < -6.02 - 10
    assert tp[4] == 0 and tp[7] == 0  # beyond the filter reach


# --- fixtures: roadmap acceptance --------------------------------------------------------------


def test_ok_prores_program_levels(measured) -> None:
    m, out = measured("ok_prores.mov")
    lines = video_lines(out)
    assert [r["f"] for r in lines] == list(range(500))
    program = lines[250:]
    assert max(r["y_above_pct"] for r in program) <= 1
    assert max(r["y_below_pct"] for r in program) <= 1
    assert all(r["y_p99"] < 68 for r in lines[125:250])  # black head
    assert m.integrity.ok and m.video.frames == 500


def test_bad_levels_frames(measured) -> None:
    _, out = measured("bad_levels.mov")
    lines = video_lines(out)
    white = lines[300:325]
    black = lines[375:400]
    assert all(r["y_above_pct"] > 90 and r["y_min"] == 975 for r in white)
    assert all(r["y_below_pct"] > 90 and r["y_max"] == 40 for r in black)
    # Neutral chroma: R = G = B = Y. 975 and 40 are out of the luma tolerance [55, 967] but inside
    # the RGB bounds [20, 984], so these frames are not gamut errors.
    assert all(r["rgb_out_pct"] == 0 for r in white + black)
    for f in (299, 325, 374, 400):
        assert lines[f]["y_above_pct"] < 1 and lines[f]["y_below_pct"] < 1


def test_bad_audio_loudness(measured, fixtures_dir) -> None:
    m, out = measured("bad_audio.mov")
    vf = m.audio.groups["VF stéréo"]
    assert -16.5 <= vf.integrated_lufs <= -15.5
    assert vf.true_peak_dbtp > -1.0
    # Same programme range measured by FFmpeg alone (tests/test_fixtures.py helper).
    i, tp = loudness(fixtures_dir / "bad_audio.mov", [0, 1], start=10)
    assert vf.integrated_lufs == pytest.approx(i, abs=0.05)
    assert vf.true_peak_dbtp == pytest.approx(tp, abs=0.1)
    # The 10 ms burst at 10:00:05:00 (t = 15 s) is located by the per-block true peak.
    blocks = audio_lines(out, "VF stéréo")
    worst = max(blocks, key=lambda b: b["tp"][0] if b["tp"][0] is not None else -math.inf)
    assert worst["t"] == 15.0 and worst["tp"][0] > -1.0


def test_classic_program_range(measured) -> None:
    m, _ = measured("ok_prores.mov")
    p = m.audio.program
    assert (p.frame_start, p.frame_end, p.start_method, p.end_method) == (250, 499, "timecode", "file")
    assert (p.tc_start, p.tc_end) == ("10:00:00:00", "10:00:09:24")
    assert (p.sample_start, p.sample_end) == (480000, 960000)
    vf = m.audio.groups["VF stéréo"]
    assert vf.integrated_lufs == pytest.approx(-23.0, abs=0.2)  # the -18 dBFS tone is excluded
    assert vf.correlation == 1.0 and vf.difference_peak_dbfs is None


def test_program_range_without_timecode(measured) -> None:
    m, _ = measured("bad_structure.mov")  # TC 00:00:00:00: the profile layout is used
    p = m.audio.program
    assert (p.frame_start, p.start_method, p.tc_start) == (250, "profile", "00:00:10:00")


def test_arte_bad_audio(measured) -> None:
    m, out = measured("arte_bad.mov", ARTE)
    p = m.audio.program
    assert (p.frame_start, p.frame_end, p.start_method) == (0, 624, "file")  # no leaders: all is programme
    vf = m.audio.groups["VF"]
    assert vf.integrated_lufs is None and vf.true_peak_dbtp is None and vf.correlation is None
    assert [t.peak_dbfs for t in m.audio.tracks if t.track in (3, 4)] == [None, None]
    assert m.audio.groups["VO"].true_peak_dbtp > -1.0
    blocks = audio_lines(out, "VF")
    assert len(blocks) == m.audio.blocks == 250
    assert all(b["peak"] == [None, None] and b["rms"] == [None, None] for b in blocks)


def test_arte_dual_mono_tracks_identical(measured) -> None:
    m, out = measured("arte_ok.mov", ARTE)
    for name in ("VO", "VF", "VI"):
        g = m.audio.groups[name]
        assert g.difference_peak_dbfs is None and g.correlation == 1.0
        assert g.integrated_lufs == pytest.approx(-23.0, abs=0.2) and g.true_peak_dbtp < -1.0
    blocks = audio_lines(out, "VO")
    assert blocks[2]["m"] is None and blocks[3]["m"] is not None
    assert blocks[28]["s"] is None and blocks[29]["s"] is not None


def test_audio_map_drives_measured_groups(fixtures_dir, tmp_path) -> None:
    from pad_guard import audio_map

    profile = load_profile(ARTE)
    mapping = audio_map.parse("VF:1-2,VO:3-4", profile)
    result = probe_file(fixtures_dir / "arte_4tracks.mov", profile, ARTE, mapping)
    m = measure.run(result, profile, tmp_path)
    assert list(m.audio.groups) == ["VF", "VO"]
    assert m.audio.groups["VF"].group.tracks == [1, 2]
    assert [t.track for t in m.audio.tracks] == [1, 2, 3, 4]


def test_measurements_reproducible(fixtures_dir, tmp_path) -> None:
    outputs = []
    for name, workers in (("a", 1), ("b", 3)):
        run(fixtures_dir / "bad_levels.mov", CLASSIC, tmp_path / name, workers)
        outputs.append([(tmp_path / name / f).read_bytes()
                        for f in (measure.MEASUREMENTS_FILE, measure.VIDEO_FILE, measure.AUDIO_FILE)])
    assert outputs[0] == outputs[1]
    header = json.loads(outputs[0][0])
    assert header["video"] == {"format": "jsonl", "file": "measurements_video.jsonl",
                               "fields": list(measure.video.FIELDS), "frames": 500, "first_field": None}
    assert header["video_settings"]["y_tolerance"] == [55, 967]


def test_no_measurable_group(fixtures_dir, tmp_path) -> None:
    # Every mapped track is missing: per-track levels are still measured, no group loudness.
    profile = load_profile(ARTE)
    from pad_guard import audio_map

    result = probe_file(fixtures_dir / "ok_prores.mov", profile, ARTE, audio_map.parse("VO:5-6", profile))
    m = measure.run(result, profile, tmp_path, workers=2)
    assert m.audio.groups == {} and [t.track for t in m.audio.tracks] == [1, 2]
    assert (tmp_path / measure.AUDIO_FILE).read_text(encoding="utf-8") == ""
