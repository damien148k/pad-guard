"""Step 1: read the container metadata with ffprobe and compare it to the profile (SPEC §4)."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any

from pad_checker import __version__, audio_map as amap, timecode
from pad_checker.audio_map import AudioMap
from pad_checker.probe.models import (
    AudioStreamInfo,
    AudioTrack,
    Check,
    ContainerInfo,
    ProbeResult,
    ProfileRef,
    SourceInfo,
    VideoInfo,
)
from pad_checker.profiles import fingerprint
from pad_checker.rules.profile import Profile

_UNKNOWN = {None, "", "unknown", "unspecified", "N/A"}

# Frame rates the measurements support until Phase 6 (docs/ROADMAP.md). Nothing else may assume
# a rate: durations and timecodes always come from the rate read in probe.json.
MEASURABLE_RATES = (Fraction(25, 1),)
_INTERLACED = {"tt", "bb", "tb", "bt"}


class ProbeError(Exception):
    """The file cannot be read at all. The message is user-facing (French)."""


def sha256_file(path: Path, chunk: int = 8 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def run_ffprobe(path: Path) -> dict[str, Any]:
    exe = shutil.which("ffprobe")
    if exe is None:
        raise ProbeError("ffprobe introuvable : installer FFmpeg 6+ et l'ajouter au PATH.")
    proc = subprocess.run(
        [exe, "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else f"code {proc.returncode}"
        raise ProbeError(f"ffprobe ne peut pas lire le fichier : {detail}")
    return json.loads(proc.stdout)


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _clean(value: Any) -> str | None:
    return None if value in _UNKNOWN else str(value)


def _fps(rate: str) -> Fraction | None:
    try:
        f = Fraction(rate)
    except (ValueError, ZeroDivisionError):
        return None
    return f if f > 0 else None


def _scan_flag(field_order: str | None) -> str:
    if field_order == "progressive":
        return "progressive"
    return "interlaced" if field_order in _INTERLACED else "unknown"


def rate_text(fps: Fraction) -> str:
    """'25/1 (25 i/s)', '30000/1001 (29,97 i/s)'."""
    per_second = f"{float(fps):.3f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{fps.numerator}/{fps.denominator} ({per_second} i/s)"


def _container(fmt: dict[str, Any], path: Path) -> ContainerInfo:
    names = fmt.get("format_name", "").split(",")
    if "mxf" in names:
        kind = "mxf"
    elif "mov" in names and path.suffix.lower() == ".mov":
        kind = "mov"
    else:
        kind = "other"
    return ContainerInfo(format_name=fmt.get("format_name", ""), kind=kind, duration_s=_float(fmt.get("duration")))


def _video(stream: dict[str, Any]) -> VideoInfo:
    duration = _float(stream.get("duration"))
    nb_frames = _int(stream.get("nb_frames"))
    source = "stream" if nb_frames is not None else None
    fps = _fps(stream.get("r_frame_rate", ""))
    if nb_frames is None and duration is not None and fps is not None:
        nb_frames = round(duration * fps)
        source = "duration"
    return VideoInfo(
        stream_index=stream["index"],
        codec_name=stream.get("codec_name", "inconnu"),
        profile=_clean(stream.get("profile")),
        pix_fmt=_clean(stream.get("pix_fmt")),
        width=_int(stream.get("width")) or 0,
        height=_int(stream.get("height")) or 0,
        r_frame_rate=stream.get("r_frame_rate", "0/0"),
        avg_frame_rate=stream.get("avg_frame_rate", "0/0"),
        fps=None if fps is None else f"{fps.numerator}/{fps.denominator}",
        field_order=_clean(stream.get("field_order")),
        scan_flag=_scan_flag(_clean(stream.get("field_order"))),
        color_primaries=_clean(stream.get("color_primaries")),
        color_transfer=_clean(stream.get("color_transfer")),
        color_space=_clean(stream.get("color_space")),
        color_range=_clean(stream.get("color_range")),
        duration_s=duration,
        nb_frames=nb_frames,
        nb_frames_source=source,
    )


def _bit_depth(stream: dict[str, Any]) -> int | None:
    for key in ("bits_per_raw_sample", "bits_per_sample"):
        value = _int(stream.get(key))
        if value:
            return value
    return None


def _audio(stream: dict[str, Any]) -> AudioStreamInfo:
    return AudioStreamInfo(
        stream_index=stream["index"],
        codec_name=stream.get("codec_name", "inconnu"),
        sample_rate=_int(stream.get("sample_rate")),
        channels=_int(stream.get("channels")) or 0,
        channel_layout=_clean(stream.get("channel_layout")),
        bit_depth=_bit_depth(stream),
        duration_s=_float(stream.get("duration")),
    )


def _timecode(info: dict[str, Any]) -> tuple[str | None, str | None]:
    """Start timecode: MOV tmcd track (or video stream tag), MXF material package (format tag)."""
    for stream in info.get("streams", []):
        if stream.get("codec_type") == "data" and "timecode" in stream.get("tags", {}):
            return stream["tags"]["timecode"], f"flux {stream['index']} (tmcd)"
    for stream in info.get("streams", []):
        if "timecode" in stream.get("tags", {}):
            return stream["tags"]["timecode"], f"flux {stream['index']} ({stream.get('codec_type')})"
    tags = info.get("format", {}).get("tags", {})
    if "timecode" in tags:
        return tags["timecode"], "conteneur"
    return None, None


def audio_tracks(streams: list[AudioStreamInfo]) -> list[AudioTrack]:
    tracks: list[AudioTrack] = []
    for stream in streams:
        for ch in range(stream.channels):
            tracks.append(AudioTrack(track=len(tracks) + 1, stream_index=stream.stream_index, channel=ch))
    return tracks


def _track_list(tracks: list[int]) -> str:
    return ", ".join(str(t) for t in tracks)


class _Checks:
    def __init__(self) -> None:
        self.items: list[Check] = []

    def add(self, id: str, label: str, type: str, expected: Any, actual: Any, ok: bool | None, refusal: bool = False):
        status = "unknown" if ok is None else ("ok" if ok else "fail")
        self.items.append(
            Check(id=id, label=label, type=type, expected=str(expected), actual=str(actual), status=status, refusal=refusal)
        )


def _check_format(c: _Checks, p: Profile, container: ContainerInfo, v: VideoInfo) -> None:
    f = p.format
    c.add("container", "Conteneur", "format", " ou ".join(f.containers), container.kind if container.kind != "other"
          else container.format_name, container.kind in f.containers)

    accepted = [(spec.codec_name, spec.profile) for spec in f.codecs]
    expected_codecs = ", ".join(f"{name} {prof}" for name, prof in accepted)
    found_codec = f"{v.codec_name} {v.profile or '(profil inconnu)'}"
    c.add("codec", "Codec et profil", "format", expected_codecs, found_codec,
          (v.codec_name, v.profile) in accepted, refusal=True)
    c.add("pix_fmt", "Format de pixel", "format", f.pix_fmt, v.pix_fmt or "inconnu", v.pix_fmt == f.pix_fmt, refusal=True)
    c.add("resolution", "Résolution", "format", f"{f.width}x{f.height}", f"{v.width}x{v.height}",
          (v.width, v.height) == (f.width, f.height))

    allowed = {_fps(r) for r in f.fps_allowed}
    r, avg = _fps(v.r_frame_rate), _fps(v.avg_frame_rate)
    c.add("frame_rate", "Cadence", "format", " ou ".join(f.fps_allowed), v.r_frame_rate, r in allowed)
    c.add("frame_rate_constant", "Cadence constante", "format", "r_frame_rate = avg_frame_rate",
          f"{v.r_frame_rate} / {v.avg_frame_rate}", r is not None and r == avg)
    c.add("frame_rate_measurable", "Cadence prise en charge par pad-checker", "format",
          " ou ".join(rate_text(x) for x in MEASURABLE_RATES), rate_text(r) if r else v.r_frame_rate,
          r in MEASURABLE_RATES, refusal=True)
    c.add("field_order", "Balayage", "format", f.field_order, v.field_order or "absent", v.field_order == f.field_order)

    for key, label in (("color_primaries", "Primaires"), ("color_transfer", "Transfert"), ("color_space", "Matrice")):
        expected, actual = getattr(f, key), getattr(v, key)
        c.add(key, f"Colorimétrie : {label.lower()}", "format", expected, actual or "non renseigné",
              None if actual is None else actual == expected)
    c.add("color_range", "Plage", "format", f.color_range, v.color_range or "non renseignée",
          None if v.color_range is None else v.color_range == f.color_range)


def _check_duration(c: _Checks, v: VideoInfo) -> None:
    fps = _fps(v.r_frame_rate)
    if v.nb_frames_source != "stream" or v.duration_s is None or fps is None:
        return
    from_duration = v.duration_s * fps
    c.add("duration_consistency", "Cohérence durée / nombre d'images", "format",
          f"{v.nb_frames} images", f"{float(from_duration):.2f} images d'après la durée ({v.duration_s:.3f} s)",
          abs(from_duration - v.nb_frames) <= 1)


def _check_timecode(c: _Checks, p: Profile, tc: str | None) -> None:
    rules = p.structure.timecode
    c.add("timecode_present", "Timecode de départ présent", "structure_timecode", "présent", tc or "absent",
          tc is not None)
    if tc is None:
        return
    c.add("timecode_start", "Timecode de départ", "structure_timecode", rules.file_start, tc, tc == rules.file_start)
    if not rules.drop_frame_allowed:
        c.add("timecode_drop_frame", "Timecode non drop frame", "structure_timecode", "non drop frame",
              "drop frame" if timecode.is_drop_frame(tc) else "non drop frame", not timecode.is_drop_frame(tc))


def _check_audio(
    c: _Checks, p: Profile, mapping: AudioMap, streams: list[AudioStreamInfo], tracks: list[AudioTrack]
) -> None:
    a = p.audio
    available = {t.track for t in tracks}
    for group in mapping.groups:
        missing = [t for t in group.tracks if t not in available]
        label = f"Groupe audio {group.name} (pistes {_track_list(group.tracks)})"
        if not missing:
            c.add(f"audio_group_{group.name}", label, "format", "présent", "présent", True)
        elif group.required:
            c.add(f"audio_group_{group.name}", label, "format", "présent",
                  f"pistes absentes : {_track_list(missing)} ({len(tracks)} piste(s) dans le fichier)", False)
        else:
            c.add(f"audio_group_{group.name}", label, "format", "facultatif", "absent", True)

    if a.max_pairs is not None:
        c.add("audio_max_pairs", "Nombre de paires audio", "format", f"≤ {a.max_pairs} paires ({2 * a.max_pairs} pistes)",
              f"{len(tracks)} piste(s)", len(tracks) <= 2 * a.max_pairs)

    allowed_depths = a.bit_depth_allowed or [a.bit_depth]
    for s in streams:
        prefix = f"Flux audio {s.stream_index}"
        c.add(f"audio_codec_{s.stream_index}", f"{prefix} : codec", "format", "PCM", s.codec_name,
              s.codec_name.startswith("pcm_"))
        c.add(f"audio_sample_rate_{s.stream_index}", f"{prefix} : fréquence", "format", f"{a.sample_rate} Hz",
              f"{s.sample_rate} Hz" if s.sample_rate else "inconnue", s.sample_rate == a.sample_rate)
        c.add(f"audio_bit_depth_{s.stream_index}", f"{prefix} : quantification", "format",
              " ou ".join(f"{d} bits" for d in allowed_depths),
              f"{s.bit_depth} bits" if s.bit_depth else "inconnue", s.bit_depth in allowed_depths)
    if a.same_bit_depth_all_tracks and streams:
        depths = sorted({s.bit_depth for s in streams}, key=lambda d: d or 0)
        c.add("audio_same_bit_depth", "Quantification identique sur toutes les pistes", "format", "identique",
              ", ".join(f"{d} bits" for d in depths), len(depths) == 1)


def _source(path: Path, known: SourceInfo | None) -> SourceInfo:
    resolved, size = str(path.resolve()), path.stat().st_size
    if known is not None and known.path == resolved and known.size_bytes == size:
        return known
    return SourceInfo(path=resolved, size_bytes=size, sha256=sha256_file(path))


def _refusal(ch: Check) -> str:
    if ch.id == "frame_rate_measurable":
        return (f"cadence {ch.actual} : pad-checker ne mesure pour l'instant que {ch.expected} "
                "(autres cadences prévues en Phase 6).")
    return f"{ch.label} : {ch.actual} n'est pas accepté (attendu : {ch.expected})."


def probe_file(
    path: str | Path, profile: Profile, profile_path: str | Path, audio_map: AudioMap | None = None,
    known: SourceInfo | None = None,
) -> ProbeResult:
    """``audio_map`` overrides the profile track groups (``--audio-map``); None = profile default.

    ``known``: source identity from a previous probe of the same file (``rerun`` with another
    profile). Its SHA-256 is kept when the path and size are unchanged, instead of reading the
    whole file again (a feature master is 100+ GB).
    """
    path = Path(path)
    mapping = audio_map or amap.from_profile(profile)
    if not path.is_file():
        raise ProbeError(f"fichier introuvable : {path}")
    info = run_ffprobe(path)
    streams = info.get("streams", [])
    videos = [s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")]
    if not videos:
        raise ProbeError("aucun flux vidéo dans le fichier.")

    container = _container(info.get("format", {}), path)
    video = _video(videos[0])
    audio = [_audio(s) for s in streams if s.get("codec_type") == "audio"]
    tracks = audio_tracks(audio)
    tc, tc_source = _timecode(info)

    c = _Checks()
    if len(videos) > 1:
        c.add("video_streams", "Nombre de flux vidéo", "format", "1", str(len(videos)), False)
    _check_format(c, profile, container, video)
    _check_duration(c, video)
    _check_timecode(c, profile, tc)
    _check_audio(c, profile, mapping, audio, tracks)

    refusals = [ch for ch in c.items if ch.refusal and ch.status != "ok"]
    profile_path = Path(profile_path)
    return ProbeResult(
        tool_version=__version__,
        profile=ProfileRef(name=profile.meta.name, version=profile.meta.version, sha256=sha256_file(profile_path),
                           status=profile.meta.status, effective_sha256=fingerprint(profile)),
        source=_source(path, known),
        container=container,
        video=video,
        audio_streams=audio,
        audio_tracks=tracks,
        audio_map=mapping,
        timecode=tc,
        timecode_source=tc_source,
        checks=c.items,
        accepted=not refusals,
        refusal_reasons=[_refusal(ch) for ch in refusals],
    )
