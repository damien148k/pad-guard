"""Step 1: read the container metadata with ffprobe and compare it to the profile (SPEC §4)."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any

from pad_guard import __version__, audio_map as amap, formats, timecode
from pad_guard.audio_map import AudioMap
from pad_guard.probe import tc_reader
from pad_guard.probe.models import (
    AudioStreamInfo,
    AudioTrack,
    Check,
    ContainerInfo,
    ProbeResult,
    ProfileRef,
    SourceInfo,
    VideoInfo,
)
from pad_guard.profiles import fingerprint
from pad_guard.rules.profile import ANY, COHERENT, Profile
from pad_guard.timecode import TimecodeFormat

_UNKNOWN = {None, "", "unknown", "unspecified", "N/A"}

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


rate_text = formats.rate_text


# Operational pattern items of the MXF operational_pattern_ul (SMPTE ST 377-1, ST 378, ST 390).
_OP1A = "0d010201.0101"
_OPATOM = "0d010201.10"


def _container(fmt: dict[str, Any], path: Path) -> ContainerInfo:
    names = fmt.get("format_name", "").split(",")
    tags = fmt.get("tags", {})
    pattern = None
    if "mxf" in names:
        kind = "mxf"
        ul = str(tags.get("operational_pattern_ul", "")).lower()
        pattern = "op1a" if _OP1A in ul else "opatom" if _OPATOM in ul else "other"
    elif "mov" in names:
        # ffprobe gives one name to the QuickTime family: the extension, else the brand, tells MP4 from MOV.
        suffix = path.suffix.lower()
        brand = str(tags.get("major_brand", "")).strip()
        if suffix in (".mov", ".mp4", ".m4v"):
            kind = "mov" if suffix == ".mov" else "mp4"
        else:
            kind = "mov" if brand in ("", "qt") else "mp4"
    else:
        kind = "other"
    return ContainerInfo(format_name=fmt.get("format_name", ""), kind=kind, duration_s=_float(fmt.get("duration")),
                         mxf_pattern=pattern)


_CONTAINER_LABELS = {"mov": "MOV", "mp4": "MP4", "mxf": "MXF"}
_PATTERN_LABELS = {"op1a": "OP1a", "opatom": "OP-Atom", "other": "autre motif"}


def container_label(container: ContainerInfo) -> str:
    """'MOV', 'MXF OP1a', 'MXF OP-Atom'."""
    if container.kind == "other":
        return container.format_name
    label = _CONTAINER_LABELS[container.kind]
    return f"{label} {_PATTERN_LABELS[container.mxf_pattern]}" if container.mxf_pattern else label


def _container_ok(container: ContainerInfo, allowed: list[str]) -> bool:
    if container.kind == "mxf":
        return "mxf" in allowed or f"mxf_{container.mxf_pattern}" in allowed
    return container.kind in allowed


def picture_label(v: VideoInfo) -> str:
    """'4:2:2 · 10 bits', 'RVB · 10 bits', with the alpha channel if any."""
    if v.sampling is None:
        return v.pix_fmt or "inconnu"
    text = f"{'RVB' if v.sampling == 'rgb' else v.sampling} · {v.bit_depth} bits"
    return text + " · canal alpha" if v.alpha else text


def _video(stream: dict[str, Any]) -> VideoInfo:
    duration = _float(stream.get("duration"))
    nb_frames = _int(stream.get("nb_frames"))
    source = "stream" if nb_frames is not None else None
    fps = _fps(stream.get("r_frame_rate", ""))
    pixel = formats.pixel_info(_clean(stream.get("pix_fmt"))) or {}
    if nb_frames is None and duration is not None and fps is not None:
        nb_frames = round(duration * fps)
        source = "duration"
    return VideoInfo(
        stream_index=stream["index"],
        codec_name=stream.get("codec_name", "inconnu"),
        profile=_clean(stream.get("profile")),
        pix_fmt=_clean(stream.get("pix_fmt")),
        bit_depth=pixel.get("bit_depth"),
        sampling=pixel.get("sampling"),
        alpha=pixel.get("alpha", False),
        width=_int(stream.get("width")) or 0,
        sar=None if _clean(stream.get("sample_aspect_ratio")) in (None, "0:1") else stream.get("sample_aspect_ratio"),
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


def _check_measurable(c: _Checks, v: VideoInfo) -> None:
    """What PAD Guard can measure (formats.py): the only checks that refuse a file."""
    c.add("decoder", "Décodeur disponible", "format", "décodeur FFmpeg pour ce codec", v.codec_name,
          formats.decoder_available(v.codec_name), refusal=True)
    c.add("pix_fmt_measurable", "Format de pixel mesurable par PAD Guard", "format",
          formats.PIX_FMTS_TEXT, v.pix_fmt or "inconnu",
          v.pix_fmt in formats.MEASURABLE_PIX_FMTS, refusal=True)
    r, avg = _fps(v.r_frame_rate), _fps(v.avg_frame_rate)
    c.add("frame_rate_measurable", "Cadence prise en charge par PAD Guard", "format",
          " ou ".join(rate_text(x) for x in formats.MEASURABLE_RATES), rate_text(r) if r else v.r_frame_rate,
          r in formats.MEASURABLE_RATES, refusal=True)
    # Variable frame rate: the frames are not evenly spaced, durations and timecodes would be wrong.
    # A rounding difference of less than one frame over the stream is not one.
    variable = r is None or avg is None or (r != avg and (v.duration_s is None or abs(r - avg) * Fraction(
        str(v.duration_s)) >= 1))
    c.add("frame_rate_variable", "Cadence fixe", "format", "cadence fixe (r_frame_rate = avg_frame_rate)",
          f"{v.r_frame_rate} / {v.avg_frame_rate}", not variable, refusal=True)
    hdr = v.color_transfer in formats.HDR_TRANSFERS or {v.color_space, v.color_primaries} & formats.WIDE_GAMUT
    if hdr:
        c.add("sdr", "Signal SDR (BT.709 ou BT.601)", "format", "SDR",
              f"transfert {v.color_transfer or '?'}, primaires {v.color_primaries or '?'}, matrice {v.color_space or '?'}",
              False, refusal=True)
    elif not formats.matrix_measurable(v.color_space):
        c.add("matrix_measurable", "Matrice de couleur mesurable par PAD Guard", "format", formats.MATRICES_TEXT,
              v.color_space, False, refusal=True)


ANY_LABEL = "tout (contrôle technique)"


def _check_format(c: _Checks, p: Profile, container: ContainerInfo, v: VideoInfo) -> None:
    """Format of the file against the profile. A value "any" (technical profile) accepts everything:
    the check is listed with what the file holds, never failed."""
    f = p.format

    def add(id_: str, label: str, type_: str, wanted, expected: str, actual: str, ok: bool | None) -> None:
        if wanted == ANY:
            c.add(id_, label, type_, ANY_LABEL, actual, True)
        else:
            c.add(id_, label, type_, expected, actual, ok)

    containers = f.containers
    add("container", "Conteneur", "format_container", containers,
        " ou ".join(containers) if containers != ANY else "", container_label(container),
        containers == ANY or _container_ok(container, containers))

    found_codec = f"{v.codec_name} {v.profile or '(profil inconnu)'}"
    if f.codecs == ANY:
        add("codec", "Codec et profil", "format_codec", ANY, "", found_codec, True)
    else:
        accepted = [(spec.codec_name, spec.profile) for spec in f.codecs]
        labels = list(dict.fromkeys(spec.label or f"{spec.codec_name} {spec.profile}" for spec in f.codecs))
        add("codec", "Codec et profil", "format_codec", f.codecs, ", ".join(labels), found_codec,
            (v.codec_name, v.profile) in accepted)
    if f.pix_fmt is not None:  # older form of the profile
        c.add("pix_fmt", "Format de pixel", "format_picture", f.pix_fmt, v.pix_fmt or "inconnu", v.pix_fmt == f.pix_fmt)
    else:
        depths, chroma = f.bit_depth_allowed, f.chroma_allowed
        add("bit_depth", "Profondeur", "format_picture", depths,
            " ou ".join(f"{b} bits" for b in depths) if depths != ANY else "",
            f"{v.bit_depth} bits" if v.bit_depth else v.pix_fmt or "inconnue", depths == ANY or v.bit_depth in depths)
        add("chroma", "Échantillonnage de la chrominance", "format_picture", chroma,
            " ou ".join("RVB" if x == "rgb" else x for x in chroma) if chroma != ANY else "",
            ("RVB" if v.sampling == "rgb" else v.sampling) or v.pix_fmt or "inconnu",
            chroma == ANY or v.sampling in chroma)
    if v.alpha:
        c.add("alpha", "Canal alpha", "alpha_channel", "aucun", "présent, ignoré par les mesures", False)
    size = ANY if ANY in (f.width, f.height) else (f.width, f.height)
    add("resolution", "Résolution", "format_resolution", size, f"{f.width}x{f.height}", f"{v.width}x{v.height}",
        (v.width, v.height) == size)

    r, avg = _fps(v.r_frame_rate), _fps(v.avg_frame_rate)
    rates = f.fps_allowed
    add("frame_rate", "Cadence", "format_frame_rate", rates, " ou ".join(rates) if rates != ANY else "",
        v.r_frame_rate, rates == ANY or r in {_fps(x) for x in rates})
    c.add("frame_rate_constant", "Cadence constante", "format_frame_rate", "r_frame_rate = avg_frame_rate",
          f"{v.r_frame_rate} / {v.avg_frame_rate}", r is not None and r == avg)
    psf = f.field_order == "psf" and v.field_order in ("progressive", *_INTERLACED)  # PsF is flagged either way
    add("field_order", "Balayage", "format", f.field_order, f.field_order, v.field_order or "absent",
        psf or v.field_order == f.field_order)

    for key, label in (("color_primaries", "Primaires"), ("color_transfer", "Transfert"), ("color_space", "Matrice")):
        expected, actual = getattr(f, key), getattr(v, key)
        allowed: tuple[str, ...] = (expected,)
        if expected == COHERENT:
            allowed, why = formats.coherent_tags(key, v.sampling == "rgb", v.height)
            expected = f"cohérente avec le fichier ({why}) : {' ou '.join(allowed)}"
        c.add(key, f"Colorimétrie : {label.lower()}", "format_color_tags", expected, actual or "non renseigné",
              None if actual is None else actual in allowed)
    add("color_range", "Plage", "format_color_tags", f.color_range, f.color_range, v.color_range or "non renseignée",
        None if v.color_range is None else v.color_range == f.color_range)


def _check_duration(c: _Checks, v: VideoInfo) -> None:
    fps = _fps(v.r_frame_rate)
    if v.nb_frames_source != "stream" or v.duration_s is None or fps is None:
        return
    from_duration = v.duration_s * fps
    c.add("duration_consistency", "Cohérence durée / nombre d'images", "format",
          f"{v.nb_frames} images", f"{float(from_duration):.2f} images d'après la durée ({v.duration_s:.3f} s)",
          abs(from_duration - v.nb_frames) <= 1)


def timecode_format(path: Path, container: ContainerInfo, v: VideoInfo, tc: str | None) -> TimecodeFormat | None:
    """Format of the start timecode: read in the file (tc_reader), else deduced from the frame rate."""
    fps = _fps(v.r_frame_rate)
    if tc is None or fps is None:
        return None
    return tc_reader.read_format(path, container.kind, fps, tc) or timecode.default_format(fps, tc)


def _check_timecode(c: _Checks, p: Profile, tc: str | None, fmt: TimecodeFormat | None) -> None:
    rules = p.structure.timecode
    c.add("timecode_present", "Timecode de départ présent", "structure_timecode", "présent", tc or "absent",
          tc is not None)
    if tc is None:
        return
    if rules.file_start == ANY:
        c.add("timecode_start", "Timecode de départ", "structure_timecode", ANY_LABEL, tc, True)
    else:
        c.add("timecode_start", "Timecode de départ", "structure_timecode", rules.file_start, tc, tc == rules.file_start)
    drop = fmt.drop_frame if fmt is not None else timecode.is_drop_frame(tc)
    if not rules.drop_frame_allowed:
        c.add("timecode_drop_frame", "Timecode non drop frame", "structure_timecode", "non drop frame",
              "drop frame" if drop else "non drop frame", not drop)


def _check_audio(
    c: _Checks, p: Profile, mapping: AudioMap, streams: list[AudioStreamInfo], tracks: list[AudioTrack],
    container: ContainerInfo,
) -> None:
    a = p.audio
    available = {t.track for t in tracks}
    if container.mxf_pattern == "opatom" and not streams:
        # MXF OP-Atom holds one essence per file: the audio is in other files, not analysed (decision
        # of Damien, 24 October 2026). Information, not a missing track.
        c.add("audio_external", "Audio (MXF OP-Atom)", "audio_not_analysed", "audio dans le fichier",
              "fichiers audio séparés (OP-Atom) : audio non analysé", False)
        return
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


def _source(path: Path, known: SourceInfo | None, hash_source: bool = True) -> SourceInfo:
    resolved, size = str(path.resolve()), path.stat().st_size
    if known is not None and known.path == resolved and known.size_bytes == size:
        return known
    return SourceInfo(path=resolved, size_bytes=size, sha256=sha256_file(path) if hash_source else "")


def _refusal(ch: Check) -> str:
    if ch.id == "frame_rate_measurable":
        return f"cadence {ch.actual} : PAD Guard ne sait mesurer que {ch.expected}."
    if ch.id == "pix_fmt_measurable":
        return f"format de pixel {ch.actual} : PAD Guard ne sait mesurer que {ch.expected}."
    if ch.id == "decoder":
        return f"codec {ch.actual} : aucun décodeur disponible, le fichier ne peut pas être lu."
    if ch.id == "sdr":
        return f"HDR ou BT.2020 ({ch.actual}) : mesures prévues en Phase 7 (BT.2100), pas encore prises en charge."
    if ch.id == "matrix_measurable":
        return f"matrice de couleur {ch.actual} : PAD Guard ne sait mesurer que {ch.expected}."
    if ch.id == "frame_rate_variable":
        return f"cadence variable ({ch.actual}) : les images ne sont pas régulièrement espacées, PAD Guard ne la mesure pas."
    return f"{ch.label} : {ch.actual} n'est pas accepté (attendu : {ch.expected})."


def probe_file(
    path: str | Path, profile: Profile, profile_path: str | Path, audio_map: AudioMap | None = None,
    known: SourceInfo | None = None, hash_source: bool = True,
) -> ProbeResult:
    """``audio_map`` overrides the profile track groups (``--audio-map``); None = profile default.

    ``known``: source identity from a previous probe of the same file (``rerun`` with another
    profile). Its SHA-256 is kept when the path and size are unchanged, instead of reading the
    whole file again (a feature master is 100+ GB).

    ``hash_source`` False: preview of the interface before the analysis, the SHA-256 of the source is
    left empty (never written to probe.json).
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
    tc_format = timecode_format(path, container, video, tc)

    c = _Checks()
    if len(videos) > 1:
        c.add("video_streams", "Nombre de flux vidéo", "format", "1", str(len(videos)), False)
    _check_measurable(c, video)
    _check_format(c, profile, container, video)
    _check_duration(c, video)
    _check_timecode(c, profile, tc, tc_format)
    _check_audio(c, profile, mapping, audio, tracks, container)

    refusals = [ch for ch in c.items if ch.refusal and ch.status != "ok"]
    profile_path = Path(profile_path)
    return ProbeResult(
        tool_version=__version__,
        profile=ProfileRef(name=profile.meta.name, version=profile.meta.version, sha256=sha256_file(profile_path),
                           status=profile.meta.status, effective_sha256=fingerprint(profile)),
        source=_source(path, known, hash_source),
        container=container,
        video=video,
        audio_streams=audio,
        audio_tracks=tracks,
        audio_map=mapping,
        timecode=tc,
        timecode_source=tc_source,
        timecode_format=tc_format,
        checks=c.items,
        accepted=not refusals,
        refusal_reasons=[_refusal(ch) for ch in refusals],
    )
