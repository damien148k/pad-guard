"""Step 3: file structure -> structure.json (SPEC §6).

Reads probe.json, measurements.json and the JSON Lines files. Most detectors work on the
per-frame measurements; the few frames that need pixels (bars recognition, letterbox samples)
and the alignment tone are decoded from the source file by seeking, never by a second full pass.
"""

from __future__ import annotations

from collections.abc import Callable
from fractions import Fraction
from pathlib import Path

import numpy as np

from pad_checker import __version__, jsonio, timecode, workdir as wd
from pad_checker.decode.video import read_frames
from pad_checker.measure.models import Measurements
from pad_checker.measure.series import GroupBlocks, VideoSeries, load_audio, load_video
from pad_checker.probe.models import ProbeResult
from pad_checker.rules.profile import Profile, require
from pad_checker.structure import bars as bars_mod, detect, letterbox as lb
from pad_checker.structure.models import (
    BarsRange,
    Finding,
    FrameRange,
    LetterboxSample,
    LetterboxSummary,
    Structure,
    StructureCheck,
    ToneMeasure,
)

Progress = Callable[[str], None]


class StructureError(Exception):
    """The structure step cannot run. The message is user-facing (French)."""


def _fmt(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def frame_silence(
    blocks: dict[str, GroupBlocks], frames: int, fps: Fraction, sample_rate: int, block: int, threshold: float
) -> np.ndarray:
    """Frames whose audio (every mapped track) stays below ``threshold`` dBFS. No audio: all True."""
    if not blocks:
        return np.ones(frames, dtype=bool)
    loud = None
    for g in blocks.values():
        level = g.peak.max(axis=1) >= threshold
        loud = level if loud is None else (loud[: level.size] | level[: loud.size])
    cum = np.concatenate([[0], np.cumsum(loud)])
    per_frame = Fraction(sample_rate) / fps
    p, q = per_frame.numerator, per_frame.denominator
    f = np.arange(frames, dtype=np.int64)
    first = np.minimum(f * p // (q * block), loud.size)
    last = np.minimum(-((-(f + 1) * p) // (q * block)), loud.size)  # exclusive, ceil
    return (cum[last] - cum[first]) == 0


class _Context:
    def __init__(self, probe: ProbeResult, m: Measurements, profile: Profile, video: VideoSeries,
                 audio: dict[str, GroupBlocks], progress: Progress | None):
        self.probe, self.m, self.profile, self.v, self.audio = probe, m, profile, video, audio
        self.progress = progress or (lambda _msg: None)
        self.fps = Fraction(m.source.fps)
        self.clock = timecode.Clock(round(self.fps), probe.timecode)
        self.frames = video.frames
        self.source = Path(probe.source.path)
        self.checks: list[StructureCheck] = []
        self.findings: list[Finding] = []
        s = profile.structure
        self.black_video = video["y_p99"] < require(profile, "structure.black.y_max", "la détection du noir")
        if m.audio is not None and audio:
            self.silent = frame_silence(
                audio, self.frames, self.fps, m.audio.settings.sample_rate, m.audio.settings.block_samples,
                require(profile, "structure.black.silence_dbfs", "la détection du noir"),
            )
        else:
            self.silent = np.ones(self.frames, dtype=bool)
        self.black = self.black_video & self.silent
        self.static = detect.static(video["d_mean"], require(profile, "structure.freeze.threshold", "les images figées"))
        self.leaders = s.leaders

    def seconds(self, frames: int) -> float:
        return float(frames / self.fps)

    def tc_range(self, a: int, b: int) -> str:
        return f"{self.clock.tc(a)} → {self.clock.tc(b)}"

    def need_source(self, purpose: str) -> Path:
        if not self.source.is_file():
            raise StructureError(f"fichier source introuvable : {self.source} (nécessaire pour {purpose})")
        return self.source

    def check(self, **kw) -> None:
        self.checks.append(StructureCheck(**kw))


# --- bars ---------------------------------------------------------------------------------


def _bars_candidates(ctx: _Context) -> list[tuple[int, int]]:
    """Held pictures of at least one second that are not black: bars are a still picture."""
    one_second = max(int(round(ctx.fps)), 2)
    out = []
    for a, b in detect.runs(ctx.static):
        first, last = max(a - 1, 0), b
        if last - first + 1 >= one_second and not ctx.black_video[(first + last) // 2]:
            out.append((first, last))
    return out


def _find_bars(ctx: _Context, patterns: list[str], tolerance: float) -> list[BarsRange]:
    candidates = _bars_candidates(ctx)
    if not candidates:
        return []
    ctx.progress(f"Recherche de mire : {len(candidates)} plan(s) fixe(s) à examiner")
    middles = {(a + b) // 2: (a, b) for a, b in candidates}
    found = []
    for frame in read_frames(ctx.need_source("la recherche de mire"), middles, ctx.probe.video.stream_index):
        pattern, error = bars_mod.best_pattern(frame, patterns)
        if error <= tolerance:
            a, b = middles[frame.index]
            found.append(BarsRange(frame_start=a, frame_end=b, pattern=pattern, tested_frame=frame.index, error=error))
    return found


def _bars_excluded(ctx: _Context, bars: list[BarsRange]) -> np.ndarray:
    mask = np.zeros(ctx.frames, dtype=bool)
    for r in bars:
        mask[r.frame_start: r.frame_end + 1] = True
    return mask


def _check_bars_classic(ctx: _Context, bars: list[BarsRange]) -> list[ToneMeasure]:
    p = ctx.profile
    purpose = "le contrôle de la mire de tête"
    pattern = require(p, "structure.bars.pattern", purpose)
    start_tc = require(p, "structure.bars.start_tc", purpose)
    min_seconds = require(p, "structure.bars.min_seconds", purpose)
    tolerance = p.structure.timecode.tolerance_frames
    if ctx.clock.start_tc:
        expected = ctx.clock.frame(start_tc)
    else:  # no usable file timecode: position expected by the profile layout
        expected = timecode.to_frames(start_tc, ctx.clock.fps) - timecode.to_frames(
            p.structure.timecode.file_start, ctx.clock.fps)
    min_frames = int(round(min_seconds * ctx.fps))
    want = f"{pattern} à {start_tc}, au moins {_fmt(min_seconds)} s"
    match = [r for r in bars if r.pattern == pattern]
    if not match:
        others = f" (mire {bars[0].pattern} trouvée)" if bars else ""
        ctx.check(id="bars", label="Mire de barres", type="structure_bars", expected=want,
                  actual=f"absente{others}", status="fail")
        return []
    r = min(match, key=lambda x: abs(x.frame_start - expected))
    ok = abs(r.frame_start - expected) <= tolerance and r.frame_end - r.frame_start + 1 >= min_frames
    ctx.check(id="bars", label="Mire de barres", type="structure_bars", expected=want,
              actual=f"{r.pattern} {ctx.tc_range(r.frame_start, r.frame_end)} ({_fmt(ctx.seconds(r.frame_end - r.frame_start + 1))} s)",
              status="ok" if ok else "fail", frame_start=r.frame_start, frame_end=r.frame_end)
    return _check_tone(ctx, r)


def _check_tone(ctx: _Context, r: BarsRange) -> list[ToneMeasure]:
    p = ctx.profile
    purpose = "le contrôle du 1 kHz de la mire"
    hz = require(p, "structure.bars.tone_hz", purpose)
    dbfs = require(p, "structure.bars.tone_dbfs", purpose)
    tol = require(p, "structure.bars.tone_tolerance_db", purpose)
    if ctx.m.audio is None:
        ctx.check(id="bars_tone", label="Son de la mire", type="structure_bars", expected=f"{_fmt(hz, 0)} Hz",
                  actual="aucune piste audio", status="fail")
        return []
    sr = ctx.m.audio.settings.sample_rate
    mapped = {t for g in ctx.probe.audio_map.groups for t in g.tracks}
    tracks = [t for t in ctx.probe.audio_tracks if t.track in mapped]
    # One second in the middle of the bars (or the whole bars if shorter).
    a = int(r.frame_start * sr / ctx.fps)
    b = int((r.frame_end + 1) * sr / ctx.fps)
    length = min(sr, b - a)
    start = (a + b - length) // 2
    tones = bars_mod.measure_tone(ctx.need_source(purpose), tracks, start, length, sr)
    for t in tones:
        ok = (t.frequency_hz is not None and abs(t.frequency_hz - hz) <= hz * bars_mod.TONE_FREQ_TOLERANCE
              and t.level_dbfs is not None and abs(t.level_dbfs - dbfs) <= tol)
        actual = "silence" if t.frequency_hz is None else f"{_fmt(t.frequency_hz, 0)} Hz, {_fmt(t.level_dbfs, 1)} dBFS"
        ctx.check(id=f"bars_tone_{t.track}", label=f"Son de la mire, piste {t.track}", type="structure_bars",
                  expected=f"{_fmt(hz, 0)} Hz, {_fmt(dbfs, 1)} dBFS ± {_fmt(tol, 1)} dB", actual=actual,
                  status="ok" if ok else "fail", frame_start=r.frame_start, frame_end=r.frame_end)
    return tones


def _check_bars_forbidden(ctx: _Context, bars: list[BarsRange]) -> None:
    if not bars:
        ctx.check(id="bars_absent", label="Pas de mire dans le fichier", type="structure_bars_present",
                  expected="aucune mire", actual="aucune mire", status="ok")
    for i, r in enumerate(bars):
        ctx.check(id=f"bars_present_{i + 1}", label="Pas de mire dans le fichier", type="structure_bars_present",
                  expected="aucune mire",
                  actual=f"mire {r.pattern} {ctx.tc_range(r.frame_start, r.frame_end)} "
                         f"({_fmt(ctx.seconds(r.frame_end - r.frame_start + 1))} s)",
                  status="fail", frame_start=r.frame_start, frame_end=r.frame_end)


# --- head, tail, programme ----------------------------------------------------------------


def _range(r: tuple[int, int] | None) -> FrameRange | None:
    return None if r is None else FrameRange(frame_start=r[0], frame_end=r[1])


def _black_text(ctx: _Context, r: FrameRange | None) -> str:
    if r is None:
        return "aucun"
    return f"{_fmt(ctx.seconds(r.frames))} s ({ctx.tc_range(r.frame_start, r.frame_end)})"


def _classic_layout(ctx: _Context, bars_mask: np.ndarray) -> tuple[FrameRange, FrameRange | None, FrameRange | None]:
    p = ctx.profile.structure
    head_min = require(ctx.profile, "structure.black.head_min_seconds", "le contrôle du noir de tête")
    tail_min = require(ctx.profile, "structure.black.tail_min_seconds", "le contrôle du noir de queue")
    content = ~(bars_mask | ctx.black_video)
    starts = np.flatnonzero(content)
    start = int(starts[0]) if starts.size else ctx.frames - 1
    tail = _range(detect.trailing_run(ctx.black))
    end = tail.frame_start - 1 if tail is not None and tail.frame_start > start else ctx.frames - 1
    head = _range(detect.run_ending_at(ctx.black, start - 1))

    ok = head is not None and ctx.seconds(head.frames) >= head_min
    ctx.check(id="head_black", label="Noir et silence de tête", type="structure_black",
              expected=f"au moins {_fmt(head_min)} s avant le programme", actual=_black_text(ctx, head),
              status="ok" if ok else "fail",
              frame_start=None if head is None else head.frame_start, frame_end=None if head is None else head.frame_end)
    seconds = 0.0 if tail is None else ctx.seconds(tail.frames)
    ctx.check(id="tail_black", label="Noir et silence de queue", type="structure_black",
              expected=f"au moins {_fmt(tail_min)} s", actual=_black_text(ctx, tail),
              status="ok" if seconds >= tail_min else "fail",
              frame_start=None if tail is None else tail.frame_start, frame_end=None if tail is None else tail.frame_end)

    want = p.timecode.program_start
    tol = p.timecode.tolerance_frames
    if ctx.clock.start_tc is None:
        ctx.check(id="program_start", label="Début du programme", type="structure_timecode",
                  expected=f"{want} ± {tol} image(s)", actual=f"image {start} (timecode du fichier inutilisable)",
                  status="unknown", frame_start=start, frame_end=start)
    else:
        offset = ctx.clock.frame(want) - start
        ctx.check(id="program_start", label="Début du programme (première image non noire après la tête)",
                  type="structure_timecode", expected=f"{want} ± {tol} image(s)", actual=ctx.clock.tc(start),
                  status="ok" if abs(offset) <= tol else "fail", frame_start=start, frame_end=start)
    return FrameRange(frame_start=start, frame_end=end), head, tail


def _no_leaders_layout(ctx: _Context) -> tuple[FrameRange, FrameRange | None, FrameRange | None]:
    head_max = require(ctx.profile, "structure.black.head_max_seconds", "le contrôle du noir de tête")
    tail_max = require(ctx.profile, "structure.black.tail_max_seconds", "le contrôle du noir de queue")
    head = _range(detect.leading_run(ctx.black))
    tail = _range(detect.trailing_run(ctx.black))
    if head is not None and tail is not None and head.frame_end >= tail.frame_start:
        tail = None  # the whole file is black: one range
    for id_, label, r, limit in (("head_black", "Noir et silence de tête", head, head_max),
                                 ("tail_black", "Noir et silence de queue", tail, tail_max)):
        seconds = 0.0 if r is None else ctx.seconds(r.frames)
        ctx.check(id=id_, label=label, type="structure_black_too_long", expected=f"au plus {_fmt(limit)} s",
                  actual=_black_text(ctx, r), status="ok" if seconds <= limit else "fail",
                  frame_start=None if r is None else r.frame_start, frame_end=None if r is None else r.frame_end)
    return FrameRange(frame_start=0, frame_end=ctx.frames - 1), head, tail


# --- frame sequence anomalies -------------------------------------------------------------


def _sequence_findings(ctx: _Context, excluded: np.ndarray, bars_mask: np.ndarray) -> None:
    p = ctx.profile.structure
    v = ctx.v
    threshold = p.freeze.threshold
    min_frames = int(round(p.freeze.min_seconds * ctx.fps))
    for a, b in detect.frozen_ranges(ctx.static, excluded, min_frames):
        ctx.findings.append(Finding(
            type="freeze", frame_start=a, frame_end=b, worst_value=float(np.nanmax(v["d_mean"][a + 1: b + 1])),
            worst_frame=a, threshold=threshold,
            detail=f"image figée pendant {_fmt(ctx.seconds(b - a + 1))} s (différence moyenne < {_fmt(threshold, 2)})",
        ))
    for k in detect.duplicates(v["d_mean"], threshold, excluded):
        ctx.findings.append(Finding(
            type="duplicate_frame", frame_start=k, frame_end=k, worst_value=float(v["d_mean"][k]), worst_frame=k,
            threshold=threshold, detail="image identique à la précédente au milieu d'un mouvement",
        ))
    for k in detect.isolated_black(ctx.black_video & ~bars_mask, v["y_mean"]):
        ctx.findings.append(Finding(
            type="isolated_black_frame", frame_start=k, frame_end=k, worst_value=float(v["y_p99"][k]), worst_frame=k,
            threshold=float(p.black.y_max), detail="image noire isolée (hors fondu)",
        ))
    if p.pse.enabled:
        window = int(round(ctx.fps))
        for a, b, worst in detect.flash_ranges(v["d_up_pct"], v["d_down_pct"], p.pse.flash_min_area_pct,
                                               window, p.pse.max_flashes_per_second):
            ctx.findings.append(Finding(
                type="pse", frame_start=a, frame_end=b, worst_value=float(worst), worst_frame=a,
                threshold=float(p.pse.max_flashes_per_second),
                detail=f"{worst} flashs en 1 s (variation de luminance > {_fmt(p.pse.flash_min_delta_pct, 0)} % "
                       f"sur plus de {_fmt(p.pse.flash_min_area_pct, 0)} % de l'image) : à vérifier avec un "
                       "analyseur Harding certifié",
            ))


# --- letterbox ----------------------------------------------------------------------------


def _letterbox(ctx: _Context, program: FrameRange, excluded: np.ndarray) -> LetterboxSummary | None:
    spec = ctx.profile.format.letterbox
    if spec is None or not spec.check:
        return None
    tolerance = require(ctx.profile, "format.letterbox.tolerance_lines", "le contrôle du format d'image")
    y_max = ctx.profile.structure.black.y_max
    step = max(int(round(lb.SAMPLE_SECONDS * ctx.fps)), 1)
    wanted = [f for f in range(program.frame_start, program.frame_end + 1, step) if not excluded[f]]
    ctx.progress(f"Format d'image : {len(wanted)} image(s) échantillonnée(s)")
    samples: list[LetterboxSample] = []
    for frame in read_frames(ctx.need_source("le contrôle du format d'image"), wanted, ctx.probe.video.stream_index):
        area = lb.active_area(frame.y, frame.index, y_max)
        if area is not None:
            samples.append(area)
    dom, share = lb.dominant(samples, tolerance)
    matched = None if dom is None else lb.classify(dom, spec, tolerance)
    expected = ", ".join(f"{f.aspect} ({f.active_lines} lignes × {f.active_pixels} px)" for f in spec.formats)
    if dom is None:
        actual, status = "aucune image exploitable", "unknown"
    else:
        actual = (f"{lb.lines(dom)} lignes (lignes {dom.top} à {dom.bottom}) × {lb.pixels(dom)} px "
                  f"(colonnes {dom.left} à {dom.right}), {_fmt(share, 0)} % des échantillons dans cette zone"
                  + (f" : format {matched}" if matched else " : aucun format du profil"))
        status = "ok" if matched else "fail"
    ctx.check(id="letterbox", label="Format d'image (lignes et pixels actifs)", type="letterbox",
              expected=f"{expected}, ± {tolerance}", actual=actual, status=status,
              frame_start=program.frame_start, frame_end=program.frame_end)
    changes = [
        f"{fmt or 'format hors profil'} de {ctx.clock.tc(a)} à {ctx.clock.tc(b)} ({n} échantillons)"
        for a, b, fmt, n in (lb.format_changes(samples, spec, tolerance, dom) if dom else [])
    ]
    return LetterboxSummary(sample_seconds=lb.SAMPLE_SECONDS, samples=samples, dominant=dom,
                            dominant_share_pct=share, matched_format=matched, changes=changes)


# --- entry point --------------------------------------------------------------------------


def analyse(probe: ProbeResult, m: Measurements, profile: Profile, workdir: Path,
            progress: Progress | None = None) -> Structure:
    video = load_video(workdir, m)
    ctx = _Context(probe, m, profile, video, load_audio(workdir, m), progress)
    s = profile.structure
    tolerance = None
    if s.bars.required or s.bars.forbidden:
        tolerance = require(profile, "structure.bars.tolerance", "la reconnaissance de la mire")
    bars: list[BarsRange] = []
    tones: list[ToneMeasure] = []
    if s.bars.required:
        bars = _find_bars(ctx, [require(profile, "structure.bars.pattern", "la mire de tête")], tolerance)
        tones = _check_bars_classic(ctx, bars)
    elif s.bars.forbidden:
        bars = _find_bars(ctx, list(bars_mod.PATTERNS), tolerance)
        _check_bars_forbidden(ctx, bars)
    bars_mask = _bars_excluded(ctx, bars)

    if s.leaders == "classic":
        program, head, tail = _classic_layout(ctx, bars_mask)
    else:
        program, head, tail = _no_leaders_layout(ctx)

    excluded = bars_mask | ctx.black_video
    _sequence_findings(ctx, excluded, bars_mask)
    letterbox = _letterbox(ctx, program, excluded)

    limitations = []
    if probe.video.field_order not in (None, "progressive"):
        limitations.append(
            f"Fichier entrelacé ({probe.video.field_order}) : images figées, images dupliquées et PSE sont "
            "analysés sur des images entières (deux trames ensemble), pas trame par trame."
        )
    if not ctx.audio:
        limitations.append("Aucun groupe audio mesuré : le noir de tête et de queue est détecté sur l'image seule.")

    return Structure(
        tool_version=__version__,
        profile=probe.profile,
        source_sha256=m.source.sha256,
        fps=m.source.fps,
        frames=ctx.frames,
        timecode_start=ctx.clock.start_tc,
        leaders=s.leaders,
        bars=bars,
        tone=tones,
        head_black=head,
        tail_black=tail,
        program=program,
        checks=ctx.checks,
        findings=sorted(ctx.findings, key=lambda f: (f.frame_start, f.type)),
        letterbox=letterbox,
        limitations=limitations,
    )


def run(workdir: Path, profile: Profile, progress: Progress | None = None) -> Structure:
    probe = wd.load(workdir, wd.PROBE, ProbeResult, "analyze")
    m = wd.load(workdir, wd.MEASUREMENTS, Measurements, "analyze")
    (workdir / wd.STRUCTURE).unlink(missing_ok=True)
    result = analyse(probe, m, profile, workdir, progress)
    jsonio.write(workdir / wd.STRUCTURE, result)
    return result
