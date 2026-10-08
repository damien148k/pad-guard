from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from pad_checker.cli import app
from pad_checker.decode.audio import AudioGroupDecoder, MissingTrackError, resolve_tracks
from pad_checker.decode.video import DecoderOpenError, VideoDecoder, read_frames
from pad_checker.probe import probe_file
from pad_checker.rules.profile import load_profile

from conftest import PROFILES, TEST_PROFILES

pytestmark = pytest.mark.fixtures

CLASSIC = TEST_PROFILES / "test_classic.yaml"
ARTE = PROFILES / "arte_hd_sdr.yaml"


@pytest.mark.parametrize("name", ["ok_prores.mov", "ok_dnxhr.mxf"])
def test_read_frames_matches_sequential(fixtures_dir, name) -> None:
    wanted = [499, 0, 7, 250, 251, 260]
    sequential = {f.index: (f.y.copy(), f.cb.copy()) for f in VideoDecoder(fixtures_dir / name).frames()
                  if f.index in wanted}
    seeked = list(read_frames(fixtures_dir / name, wanted))
    assert [f.index for f in seeked] == sorted(wanted)
    for f in seeked:
        assert np.array_equal(f.y, sequential[f.index][0]) and np.array_equal(f.cb, sequential[f.index][1])
    assert list(read_frames(fixtures_dir / name, [600])) == []  # beyond the end


@pytest.mark.parametrize("name", ["ok_prores.mov", "ok_dnxhr.mxf"])
def test_decode_all_frames(fixtures_dir, name) -> None:
    decoder = VideoDecoder(fixtures_dir / name, frames_expected=500)
    count = 0
    for frame in decoder.frames():
        assert frame.index == count
        assert frame.y.dtype == np.uint16 and frame.y.shape == (1080, 1920)
        assert frame.cb.shape == frame.cr.shape == (1080, 960)
        if frame.index == 200:  # black head: exactly 0 % (Y=64), neutral chroma
            assert (frame.y == 64).all() and (frame.cb == 512).all() and (frame.cr == 512).all()
        if frame.index == 0:  # EBU 75 % bars: 100 % white bar, 75 % colours
            assert 900 <= frame.y.max() <= 945
        count += 1
    assert count == 500
    assert decoder.integrity.ok


def test_decode_levels(fixtures_dir) -> None:
    wanted = {300: 975, 324: 975, 375: 40, 399: 40}
    for frame in VideoDecoder(fixtures_dir / "bad_levels.mov").frames():
        if frame.index in wanted:
            assert (frame.y == wanted[frame.index]).all()
        if frame.index > 400:
            break


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    for frame in VideoDecoder(path).frames():
        if frame.index % 10 == 0:
            h.update(np.ascontiguousarray(frame.y).tobytes())
            h.update(np.ascontiguousarray(frame.cb).tobytes())
            h.update(np.ascontiguousarray(frame.cr).tobytes())
    return h.hexdigest()


def test_decode_deterministic(fixtures_dir) -> None:
    assert _digest(fixtures_dir / "ok_prores.mov") == _digest(fixtures_dir / "ok_prores.mov")


def test_corrupt_file_detected(fixtures_dir, tmp_path) -> None:
    data = bytearray((fixtures_dir / "ok_prores.mov").read_bytes())
    mid = len(data) // 2
    data[mid:mid + 200_000] = bytes((i * 7) & 0xFF for i in range(200_000))
    path = tmp_path / "corrupt.mov"
    path.write_bytes(data)

    decoder = VideoDecoder(path, frames_expected=500)
    for _ in decoder.frames():
        pass
    report = decoder.integrity
    assert not report.ok
    assert report.errors
    assert report.frames_decoded < 500 or report.pts_discontinuities


def test_truncated_mxf_detected(fixtures_dir, tmp_path) -> None:
    data = (fixtures_dir / "ok_dnxhr.mxf").read_bytes()
    path = tmp_path / "truncated.mxf"
    path.write_bytes(data[: len(data) // 2])
    decoder = VideoDecoder(path, frames_expected=500)
    for _ in decoder.frames():
        pass
    assert not decoder.integrity.ok
    assert decoder.integrity.frames_decoded < 500


def test_truncated_mov_cannot_open(fixtures_dir, tmp_path) -> None:
    data = (fixtures_dir / "ok_prores.mov").read_bytes()
    path = tmp_path / "truncated.mov"
    path.write_bytes(data[: len(data) // 2])  # the moov atom is at the end
    with pytest.raises(DecoderOpenError, match="impossible d'ouvrir"):
        next(VideoDecoder(path).frames())


def _group(fixtures_dir: Path, name: str, profile_path: Path, group_name: str):
    profile = load_profile(profile_path)
    result = probe_file(fixtures_dir / name, profile, profile_path)
    group = next(g for g in profile.audio.groups if g.name == group_name)
    return AudioGroupDecoder(fixtures_dir / name, resolve_tracks(result.audio_tracks, group.tracks))


def _collect(decoder: AudioGroupDecoder) -> np.ndarray:
    position, parts = 0, []
    for start, block in decoder.blocks():
        assert start == position
        assert block.dtype == np.float32 and block.shape[1] <= decoder.block_samples
        position += block.shape[1]
        parts.append(block)
    return np.concatenate(parts, axis=1)


def test_audio_stereo_stream(fixtures_dir) -> None:
    samples = _collect(_group(fixtures_dir, "ok_prores.mov", CLASSIC, "VF stéréo"))
    assert samples.shape == (2, 20 * 48000)
    tone = samples[:, : 5 * 48000]
    assert 20 * np.log10(np.abs(tone).max()) == pytest.approx(-18.0, abs=0.01)
    assert not samples[:, 5 * 48000 : 10 * 48000].any()  # digital silence under the black


def test_audio_mono_streams_aligned(fixtures_dir) -> None:
    for group in ("VO", "VF", "VI"):
        samples = _collect(_group(fixtures_dir, "arte_ok.mov", ARTE, group))
        assert samples.shape == (2, 20 * 48000)
        # Same signal written on L and R (two separate mono streams): must match sample for sample.
        assert np.array_equal(samples[0], samples[1])


def test_audio_silent_pair(fixtures_dir) -> None:
    samples = _collect(_group(fixtures_dir, "arte_bad.mov", ARTE, "VF"))
    assert samples.shape == (2, 25 * 48000)
    assert not samples.any()


def test_audio_missing_tracks(fixtures_dir) -> None:
    profile = load_profile(ARTE)
    result = probe_file(fixtures_dir / "ok_prores.mov", profile, ARTE)
    with pytest.raises(MissingTrackError, match="3, 4"):
        resolve_tracks(result.audio_tracks, [3, 4])


def test_benchmark_cli(fixtures_dir, tmp_path) -> None:
    result = CliRunner().invoke(
        app,
        ["analyze", str(fixtures_dir / "ok_dnxhr.mxf"), "--profile", str(CLASSIC), "--out", str(tmp_path), "--benchmark"],
    )
    assert result.exit_code == 0, result.output
    assert "500 images" in result.output and "temps réel" in result.output
    assert "Intégrité : OK" in result.output
