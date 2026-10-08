"""Step 2: decode every frame and every audio sample, write measurements.json (SPEC §5).

Reads only probe.json (as a :class:`ProbeResult`) and the profile, so it can be rerun alone.
Outputs, in the working directory:

* ``measurements_video.jsonl``: one line per frame (``measure.video.FIELDS``), streamed;
* ``measurements_audio.jsonl``: one line per 100 ms block and per track group;
* ``measurements.json``: header, integrity, settings, programme range, global audio values.
  Written last: its presence means the two other files are complete.
"""

from __future__ import annotations

import json
import os
from array import array
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from pad_checker import __version__, jsonio
from pad_checker.decode.video import VideoDecoder
from pad_checker.measure import audio as am
from pad_checker.measure.models import (
    AudioSection,
    AudioSettings,
    Measurements,
    MeasuredSource,
    ProgramRange,
    VideoSection,
    VideoSettings,
)
from pad_checker.measure.program import program_range
from pad_checker.measure.video import FIELDS, MeasureSetupError, VideoLimits, measure_frames
from pad_checker.probe.models import ProbeResult
from pad_checker.rules.profile import Profile

VIDEO_FILE = "measurements_video.jsonl"
AUDIO_FILE = "measurements_audio.jsonl"
MEASUREMENTS_FILE = "measurements.json"

Progress = Callable[[int], None]

__all__ = ["MeasureSetupError", "am", "default_workers", "run"]


def default_workers() -> int:
    """Half the logical CPUs (the decoder threads use the rest), at most 8: beyond, no gain measured."""
    return max(1, min(8, (os.cpu_count() or 2) // 2))


def _line(record: dict) -> str:
    return json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n"


def run(
    probe: ProbeResult,
    profile: Profile,
    out_dir: Path,
    workers: int | None = None,
    progress: Progress | None = None,
) -> Measurements:
    limits = VideoLimits.from_profile(profile)
    source = Path(probe.source.path)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / MEASUREMENTS_FILE).unlink(missing_ok=True)

    decoder = VideoDecoder(source, stream_index=probe.video.stream_index, frames_expected=probe.video.nb_frames)
    y_p99 = array("H")
    with (out_dir / VIDEO_FILE).open("w", encoding="utf-8", newline="\n") as f:
        for rec in measure_frames(decoder.frames(), limits, workers or default_workers()):
            f.write(_line(rec))
            y_p99.append(rec["y_p99"])
            if progress:
                progress(len(y_p99))
    integrity = decoder.integrity

    audio = _measure_audio(probe, profile, out_dir, y_p99, len(y_p99)) if probe.audio_tracks else None
    if audio is None:
        (out_dir / AUDIO_FILE).unlink(missing_ok=True)

    result = Measurements(
        tool_version=__version__,
        source=MeasuredSource(
            path=probe.source.path, sha256=probe.source.sha256, frames=probe.video.nb_frames,
            fps=probe.video.r_frame_rate,
        ),
        profile=probe.profile,
        integrity=integrity,
        video_settings=VideoSettings(
            y_legal=limits.y_legal, y_tolerance=limits.y_tolerance, rgb=limits.rgb,
            prefilter_taps=limits.prefilter_taps, matrix=limits.matrix,
        ),
        video=VideoSection(file=VIDEO_FILE, fields=list(FIELDS), frames=len(y_p99)),
        audio=audio,
    )
    jsonio.write(out_dir / MEASUREMENTS_FILE, result)
    return result


def _measure_audio(
    probe: ProbeResult, profile: Profile, out_dir: Path, y_p99: array, frames: int
) -> AudioSection:
    rates = {s.sample_rate for s in probe.audio_streams}
    if len(rates) != 1 or None in rates:
        raise am.AudioMeasureError(f"fréquences d'échantillonnage différentes ou inconnues selon les flux : {rates}")
    sample_rate = rates.pop()
    if sample_rate % 10:
        raise am.AudioMeasureError(f"fréquence d'échantillonnage {sample_rate} Hz : blocs de 100 ms impossibles")
    block = sample_rate // 10
    program: ProgramRange = program_range(probe, profile, y_p99, frames, sample_rate)
    span = (program.sample_start, program.sample_end)

    tracks = probe.audio_tracks
    position = {t.track: i for i, t in enumerate(tracks)}
    depth = {s.stream_index: s.bit_depth for s in probe.audio_streams}
    # Groups whose tracks are missing fail in probe.json and cannot be measured.
    groups = [g for g in probe.audio_map.groups if all(t in position for t in g.tracks)]
    pairs = [g for g in groups if len(g.tracks) == 2]
    pair_index = {g.name: i for i, g in enumerate(pairs)}

    levels = am.LevelPass(
        path=Path(probe.source.path),
        tracks=tracks,
        bit_depths=[depth[t.stream_index] for t in tracks],
        pairs=[(position[g.tracks[0]], position[g.tracks[1]]) for g in pairs],
        block=block,
        program=span,
    )
    full: dict[str, am.LoudnessCurve] = {}
    prog: dict[str, am.LoudnessCurve] = {}
    with ThreadPoolExecutor(max_workers=1) as pool:
        # FFmpeg reads the file in its own process while the NumPy pass runs here.
        loudness = (
            pool.submit(am.ffmpeg_loudness, Path(probe.source.path), probe.audio_streams, groups, block, span)
            if groups else None
        )
        levels.run()
        if loudness is not None:
            full, prog = loudness.result()

    with (out_dir / AUDIO_FILE).open("w", encoding="utf-8", newline="\n") as f:
        for g in groups:
            pos = [position[t] for t in g.tracks]
            for rec in am.block_lines(g, levels, pos, pair_index.get(g.name), full[g.name], sample_rate):
                f.write(_line(rec))

    return AudioSection(
        file=AUDIO_FILE,
        fields=list(am.BLOCK_FIELDS),
        settings=AudioSettings(sample_rate=sample_rate, block_samples=block),
        program=program,
        tracks=am.track_levels(levels),
        groups={
            g.name: am.group_loudness(g, levels, [position[t] for t in g.tracks], pair_index.get(g.name), prog[g.name])
            for g in groups
        },
        blocks=int(levels.blocks["count"].shape[0]) if "count" in levels.blocks else 0,
        decode_errors=levels.errors,
    )
