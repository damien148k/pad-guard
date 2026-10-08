from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pad_checker.cli import EXIT_NOT_IMPLEMENTED, EXIT_REFUSED, EXIT_USAGE, app
from pad_checker.probe import ProbeError, probe_file
from pad_checker.probe.models import AudioStreamInfo
from pad_checker.probe.probe import audio_tracks
from pad_checker.rules.profile import load_profile

from conftest import PROFILES, TEST_PROFILES

pytestmark = pytest.mark.fixtures

CLASSIC = TEST_PROFILES / "test_classic.yaml"
ARTE = PROFILES / "arte_hd_sdr.yaml"


def probe(path: Path, profile_path: Path = CLASSIC):
    return probe_file(path, load_profile(profile_path), profile_path)


def failed(result) -> dict[str, str]:
    return {c.id: c.status for c in result.checks if c.status != "ok"}


def test_ok_prores(fixtures_dir) -> None:
    r = probe(fixtures_dir / "ok_prores.mov")
    assert r.accepted and r.refusal_reasons == []
    assert r.timecode == "09:59:50:00"
    assert r.video.pix_fmt == "yuv422p10le"
    assert r.video.nb_frames == 500 and r.video.nb_frames_source == "stream"
    assert failed(r) == {}
    assert [(t.track, t.stream_index, t.channel) for t in r.audio_tracks] == [(1, 1, 0), (2, 1, 1)]


def test_probe_json_content(fixtures_dir, tmp_path) -> None:
    result = CliRunner().invoke(
        app, ["analyze", str(fixtures_dir / "ok_prores.mov"), "--profile", str(CLASSIC), "--out", str(tmp_path)]
    )
    assert result.exit_code == EXIT_NOT_IMPLEMENTED  # probe done, measures come in Phase 2
    assert "probe.json" in result.output
    data = json.loads((tmp_path / "probe.json").read_text(encoding="utf-8"))
    assert data["timecode"] == "09:59:50:00"
    assert data["video"]["pix_fmt"] == "yuv422p10le"
    assert data["video"]["nb_frames"] == 500
    assert data["schema_version"] == 1 and data["tool_version"]
    assert len(data["source"]["sha256"]) == 64


def test_probe_json_reproducible(fixtures_dir, tmp_path) -> None:
    outputs = []
    for run in ("a", "b"):
        CliRunner().invoke(
            app, ["analyze", str(fixtures_dir / "arte_ok.mov"), "--profile", str(ARTE), "--out", str(tmp_path / run)]
        )
        outputs.append((tmp_path / run / "probe.json").read_bytes())
    assert outputs[0] == outputs[1]


def test_ok_dnxhr_mxf(fixtures_dir) -> None:
    r = probe(fixtures_dir / "ok_dnxhr.mxf")
    assert r.accepted
    assert r.container.kind == "mxf"
    assert (r.video.codec_name, r.video.profile) == ("dnxhd", "DNXHR HQX")
    assert r.video.nb_frames == 500 and r.video.nb_frames_source == "duration"
    assert r.timecode == "09:59:50:00" and r.timecode_source == "conteneur"
    assert failed(r) == {}


def test_wrong_codec_refused(fixtures_dir) -> None:
    r = probe(fixtures_dir / "wrong_codec.mov")
    assert not r.accepted
    assert failed(r) == {"codec": "fail"}
    (reason,) = r.refusal_reasons
    assert "prores LT" in reason
    assert "prores HQ" in reason and "dnxhd DNXHR HQX" in reason


def test_wrong_codec_cli(fixtures_dir, tmp_path) -> None:
    result = CliRunner().invoke(
        app, ["analyze", str(fixtures_dir / "wrong_codec.mov"), "--profile", str(CLASSIC), "--out", str(tmp_path)]
    )
    assert result.exit_code == EXIT_REFUSED
    output = " ".join(result.output.split())  # Rich wraps long lines
    assert "Fichier refusé" in output
    assert "Codec et profil : prores LT n'est pas accepté (attendu : prores HQ, dnxhd DNXHR HQX)" in output


def test_bad_structure_timecode(fixtures_dir) -> None:
    r = probe(fixtures_dir / "bad_structure.mov")
    assert r.accepted
    assert r.timecode == "00:00:00:00"
    assert failed(r) == {"timecode_start": "fail"}


def test_arte_ok(fixtures_dir) -> None:
    r = probe(fixtures_dir / "arte_ok.mov", ARTE)
    assert r.accepted
    assert failed(r) == {}
    # Six mono streams: track n is stream n, channel 0.
    assert [(t.track, t.stream_index, t.channel) for t in r.audio_tracks] == [(n, n, 0) for n in range(1, 7)]


def test_arte_profile_on_classic_file(fixtures_dir) -> None:
    r = probe(fixtures_dir / "ok_prores.mov", ARTE)
    assert r.accepted  # right codec, wrong delivery
    # VF and VI are optional for Arte: only the missing VO pair would fail.
    assert failed(r) == {"timecode_start": "fail"}
    assert r.audio_map.source == "profile"


def test_arte_4_mono_tracks_profile_map(fixtures_dir) -> None:
    r = probe(fixtures_dir / "arte_4tracks.mov", ARTE)
    assert r.accepted
    assert failed(r) == {}
    assert [(t.track, t.stream_index, t.channel) for t in r.audio_tracks] == [(n, n, 0) for n in range(1, 5)]
    statuses = {c.id: (c.expected, c.actual) for c in r.checks}
    assert statuses["audio_group_VI"] == ("facultatif", "absent")


def _analyze(fixture: Path, out: Path, *extra: str):
    return CliRunner().invoke(app, ["analyze", str(fixture), "--profile", str(ARTE), "--out", str(out), *extra])


def test_arte_4_mono_tracks_audio_map(fixtures_dir, tmp_path) -> None:
    result = _analyze(fixtures_dir / "arte_4tracks.mov", tmp_path, "--audio-map", "VO:1-2,VF:3-4")
    assert result.exit_code == EXIT_NOT_IMPLEMENTED, result.output
    assert "Groupes audio (ligne de commande) : VO 1-2, VF 3-4" in " ".join(result.output.split())
    data = json.loads((tmp_path / "probe.json").read_text(encoding="utf-8"))
    assert data["audio_map"] == {
        "source": "command_line",
        "spec": "VO:1-2,VF:3-4",
        "groups": [
            {"name": "VO", "tracks": [1, 2], "layout": "stereo", "required": True},
            {"name": "VF", "tracks": [3, 4], "layout": "stereo", "required": True},
        ],
    }
    ids = {c["id"]: c["status"] for c in data["checks"]}
    assert ids["audio_group_VO"] == ids["audio_group_VF"] == "ok"
    assert "audio_group_VI" not in ids  # the command-line map replaces the profile groups


def test_audio_map_groups_are_required(fixtures_dir, tmp_path) -> None:
    result = _analyze(fixtures_dir / "arte_4tracks.mov", tmp_path, "--audio-map", "VO:1-2,VF:3-4,VI:5-6")
    data = json.loads((tmp_path / "probe.json").read_text(encoding="utf-8"))
    vi = next(c for c in data["checks"] if c["id"] == "audio_group_VI")
    assert vi["status"] == "fail" and "5, 6" in vi["actual"]
    assert result.exit_code == EXIT_NOT_IMPLEMENTED  # a failed check is a rule matter, not a refusal


def test_audio_map_profile_default_in_probe_json(fixtures_dir, tmp_path) -> None:
    _analyze(fixtures_dir / "arte_4tracks.mov", tmp_path)
    data = json.loads((tmp_path / "probe.json").read_text(encoding="utf-8"))
    assert data["audio_map"]["source"] == "profile" and data["audio_map"]["spec"] is None
    assert [g["name"] for g in data["audio_map"]["groups"]] == ["VO", "VF", "VI"]


def test_audio_map_invalid_cli(fixtures_dir, tmp_path) -> None:
    result = _analyze(fixtures_dir / "arte_4tracks.mov", tmp_path, "--audio-map", "VO:1-2,VF:2-3")
    assert result.exit_code == EXIT_USAGE
    assert "plusieurs groupes" in " ".join(result.output.split())
    assert not (tmp_path / "probe.json").exists()


def test_missing_color_tags(tmp_path) -> None:
    path = tmp_path / "untagged.mov"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=1920x1080:r=25:d=0.2",
         "-vf", "format=yuv422p10le", "-c:v", "prores_ks", "-profile:v", "3", str(path)],
        check=True,
    )
    r = probe(path)
    statuses = {c.id: c.status for c in r.checks}
    assert statuses["color_primaries"] == "unknown"
    assert statuses["color_transfer"] == "unknown"
    assert statuses["timecode_present"] == "fail"
    assert "timecode_start" not in statuses
    assert statuses["audio_group_VF stéréo"] == "fail"


def test_unreadable_file(tmp_path) -> None:
    path = tmp_path / "pas_une_video.mov"
    path.write_text("ceci n'est pas une vidéo", encoding="utf-8")
    with pytest.raises(ProbeError, match="ffprobe ne peut pas lire"):
        probe(path)
    result = CliRunner().invoke(app, ["analyze", str(path), "--profile", str(CLASSIC), "--out", str(tmp_path / "o")])
    assert result.exit_code == EXIT_REFUSED


def test_missing_file(tmp_path) -> None:
    with pytest.raises(ProbeError, match="introuvable"):
        probe(tmp_path / "absent.mov")


def test_audio_track_numbering_mixed_streams() -> None:
    def stream(index: int, channels: int) -> AudioStreamInfo:
        return AudioStreamInfo(stream_index=index, codec_name="pcm_s24le", sample_rate=48000, channels=channels,
                               channel_layout=None, bit_depth=24, duration_s=None)

    tracks = audio_tracks([stream(1, 2), stream(2, 1), stream(4, 1)])
    assert [(t.track, t.stream_index, t.channel) for t in tracks] == [(1, 1, 0), (2, 1, 1), (3, 2, 0), (4, 4, 0)]
