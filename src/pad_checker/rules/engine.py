"""Step 4: rules -> events.json + verdict.json (SPEC §7).

Collects every anomaly (failed probe and structure checks, structure findings, out-of-range
frames, audio blocks, integrity errors), aggregates frames into events, gives each event the
severity of the profile chain ``rules.severity.<type>`` and computes the verdict and score.
Everything here is deterministic: same JSON in, same JSON out.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

import numpy as np

from pad_checker import __version__, jsonio, timecode, workdir as wd
from pad_checker.audio_map import tracks_text
from pad_checker.labels import SEVERITY_ORDER, number, type_label
from pad_checker.measure.models import Measurements
from pad_checker.measure.series import GroupBlocks, VideoSeries, block_frames, load_audio, load_video
from pad_checker.probe.models import ProbeResult
from pad_checker.rules import expr
from pad_checker.rules.models import Event, Events, Verdict
from pad_checker.rules.profile import EVENT_FIELDS, AudioGroup, LoudnessRules, Profile, Severity, require
from pad_checker.structure import detect
from pad_checker.structure.models import Structure


class RulesError(Exception):
    """The rules cannot be applied. The message is user-facing (French)."""


@dataclass
class Draft:
    type: str
    title: str
    source: str
    scope: str
    frame_start: int
    frame_end: int
    value_text: str
    threshold_text: str
    worst_value: float | None = None
    worst_frame: int | None = None
    threshold: float | None = None
    area_pct_max: float | None = None
    group: str | None = None
    detail: str = ""
    occurrences: int | None = None
    severity: Severity | None = None  # fixed by the profile outside the severity chains


def merge(ranges: Iterable[tuple[int, int]], gap: int) -> list[tuple[int, int]]:
    """Merge ranges separated by fewer than ``gap`` clean frames (SPEC §7.1, merge_gap_frames)."""
    out: list[tuple[int, int]] = []
    for a, b in sorted(ranges):
        if out and a - out[-1][1] - 1 < gap:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _pct(value: float, digits: int = 2) -> str:
    return f"{number(value, digits)} %"


def _db(value: float | None, unit: str) -> str:
    return "silence numérique" if value is None or value == -math.inf else f"{number(value, 1)} {unit}"


_ERRNO = re.compile(r"^\[Errno -?\d+\]\s*")
_LAST_LOG = re.compile(r"last error log:\s*\[([^\]@ ]+)[^\]]*\]\s*(.+)$")


def error_key(message: str) -> str:
    """Normalised decoder error: the exception and the FFmpeg log of one bad packet become the same."""
    m = _LAST_LOG.search(message)
    if m:
        return f"{m.group(1)}: {m.group(2).strip()}"
    return _ERRNO.sub("", message).strip()


def _frames_list(frames: list[int], limit: int = 10) -> str:
    shown = ", ".join(str(f) for f in frames[:limit])
    return shown + (f" … (+{len(frames) - limit})" if len(frames) > limit else "")


def severity_types(profile: Profile, groups: list[AudioGroup]) -> set[str]:
    """Event types an analysis with ``profile`` and these measured track groups can produce."""
    s = profile.structure
    types = {"format", "structure_timecode", "integrity", "white_clip", "black_crush", "gamut", "freeze",
             "duplicate_frame", "isolated_black_frame"}
    if s.pse.enabled:
        types.add("pse")
    if s.bars.required:
        types.add("structure_bars")
    elif s.bars.forbidden:
        types.add("structure_bars_present")
    types.add("structure_black" if s.leaders == "classic" else "structure_black_too_long")
    if profile.format.letterbox is not None and profile.format.letterbox.check:
        types.add("letterbox")
    if groups:
        types |= {"audio_loudness", "audio_true_peak", "audio_silence"}
        if any(len(g.tracks) == 2 for g in groups):
            types.add("audio_phase")
        loud = profile.audio.loudness
        sets = [loud.long] + ([loud.short] if loud.short else [])
        if any(r.lra_max_lu is not None for r in sets):
            types.add("audio_lra")
        if any(r.short_term_dialogue_excursion_lu is not None or r.short_term_max_lufs is not None
               or r.short_term_excursion_above_lu is not None for r in sets):
            types.add("audio_short_term_excursion")
        if profile.audio.dual_mono_must_be_identical and any(g.layout == "dual_mono" for g in groups):
            types.add("audio_dual_mono_mismatch")
    if profile.audio.no_silent_tracks:
        types.add("audio_silent_track")
    return types


class Engine:
    def __init__(self, probe: ProbeResult, m: Measurements, structure: Structure, profile: Profile,
                 video: VideoSeries, audio: dict[str, GroupBlocks]):
        self.probe, self.m, self.st, self.p, self.v, self.blocks = probe, m, structure, profile, video, audio
        self.fps = Fraction(m.source.fps)
        self.clock = timecode.Clock(round(self.fps), structure.timecode_start)
        self.frames = video.frames
        self.drafts: list[Draft] = []
        self.bars = np.zeros(self.frames, dtype=bool)
        for r in structure.bars:
            self.bars[r.frame_start: r.frame_end + 1] = True

    @property
    def last(self) -> int:
        return self.frames - 1

    def seconds(self, frames: int) -> float:
        return float(frames / self.fps)

    def add(self, **kw) -> None:
        self.drafts.append(Draft(**kw))

    def aggregate(self, event_type: str, mask: np.ndarray) -> list[tuple[int, int]]:
        ranges = merge(detect.runs(mask), self.p.rules.merge_gap_frames)
        minimum = self.p.rules.min_event_frames.get(event_type, 1)
        return [(a, b) for a, b in ranges if b - a + 1 >= minimum]

    # --- probe, structure, integrity ------------------------------------------------------

    def probe_checks(self) -> None:
        unknown_severity = self.p.format.unknown_color_tags_severity
        for c in self.probe.checks:
            if c.status == "ok" or (c.status == "unknown" and not c.id.startswith("color_")):
                continue
            self.add(type=c.type, title=c.label, source="probe", scope="file", frame_start=0, frame_end=self.last,
                     value_text=c.actual, threshold_text=c.expected,
                     detail="balise absente ou « unknown »" if c.status == "unknown" else "",
                     severity=unknown_severity if c.status == "unknown" else None)

    def structure_checks(self) -> None:
        for c in self.st.checks:
            if c.status != "fail":
                continue
            ranged = c.frame_start is not None
            self.add(type=c.type, title=c.label, source="structure", scope="range" if ranged else "file",
                     frame_start=c.frame_start if ranged else 0, frame_end=c.frame_end if ranged else self.last,
                     value_text=c.actual, threshold_text=c.expected, worst_value=c.worst_value,
                     threshold=c.threshold)

    def structure_findings(self) -> None:
        by_type: dict[str, list] = {}
        for f in self.st.findings:
            by_type.setdefault(f.type, []).append(f)
        gap = self.p.rules.merge_gap_frames
        for event_type, findings in by_type.items():
            minimum = self.p.rules.min_event_frames.get(event_type, 1)
            for a, b in merge(((f.frame_start, f.frame_end) for f in findings), gap):
                if b - a + 1 < minimum:
                    continue
                inside = [f for f in findings if a <= f.frame_start and f.frame_end <= b]
                worst = max(inside, key=lambda f: -math.inf if f.worst_value is None else f.worst_value)
                if event_type == "freeze":
                    value, limit = f"{number(self.seconds(b - a + 1), 1)} s", \
                        f"< {number(self.p.structure.freeze.min_seconds, 1)} s"
                elif event_type == "pse":
                    value, limit = f"{int(worst.worst_value)} flashs/s", \
                        f"≤ {self.p.structure.pse.max_flashes_per_second} flashs/s"
                elif event_type == "isolated_black_frame":
                    value, limit = f"y_p99 = {int(worst.worst_value)}", f"noir si y_p99 < {self.p.structure.black.y_max}"
                else:
                    value, limit = f"différence {number(worst.worst_value, 3)}", \
                        f"< {number(self.p.structure.freeze.threshold, 2)}"
                count = f" ({len(inside)} occurrences)" if len(inside) > 1 else ""
                self.add(type=event_type, title=type_label(event_type), source="structure", scope="range",
                         frame_start=a, frame_end=b, value_text=value, threshold_text=limit,
                         worst_value=worst.worst_value, worst_frame=worst.worst_frame, threshold=worst.threshold,
                         detail=worst.detail + count)

    def integrity(self) -> None:
        integ = self.m.integrity
        if integ.frames_expected is not None and integ.frames_expected != integ.frames_decoded:
            self.add(type="integrity", title="Nombre d'images décodées", source="integrity", scope="file",
                     frame_start=0, frame_end=self.last, value_text=f"{integ.frames_decoded} images",
                     threshold_text=f"{integ.frames_expected} images annoncées par le conteneur")
        keys: dict[str, set[int]] = {}
        for err in integ.errors:
            keys.setdefault(error_key(err.message), set()).add(err.after_frame)
        for key, frames in sorted(keys.items(), key=lambda kv: (min(kv[1]), kv[0])):
            ordered = sorted(frames)
            a, b = min(ordered[0], self.last), min(ordered[-1], self.last)
            self.add(type="integrity", title=f"Erreur de décodage : {key}", source="integrity", scope="range",
                     frame_start=a, frame_end=b, value_text=f"{len(ordered)} image(s)", threshold_text="aucune erreur",
                     occurrences=len(ordered), detail=f"image(s) {_frames_list(ordered)}")
        for a, b in merge(((f, f) for f in integ.pts_discontinuities), self.p.rules.merge_gap_frames):
            inside = [f for f in integ.pts_discontinuities if a <= f <= b]
            self.add(type="integrity", title="Discontinuité de timestamp (image manquante ou dupliquée)",
                     source="integrity", scope="range", frame_start=a, frame_end=b,
                     value_text=f"{len(inside)} saut(s)", threshold_text="aucun saut", occurrences=len(inside),
                     detail=f"image(s) {_frames_list(inside)}")
        if self.m.audio is not None and self.m.audio.decode_errors:
            audio_keys: dict[str, int] = {}
            for msg in self.m.audio.decode_errors:
                key = error_key(msg)
                audio_keys[key] = audio_keys.get(key, 0) + 1
            for key, n in sorted(audio_keys.items()):
                self.add(type="integrity", title=f"Erreur de décodage audio : {key}", source="integrity",
                         scope="file", frame_start=0, frame_end=self.last, value_text=f"{n} occurrence(s)",
                         threshold_text="aucune erreur", occurrences=n)

    # --- video levels ---------------------------------------------------------------------

    def levels(self) -> None:
        area = self.p.video.max_out_of_range_area_pct
        s = self.m.video_settings
        lo, hi = s.y_legal

        def code(c: float) -> str:
            return f"{int(c)} ({number(100 * (c - lo) / (hi - lo), 1)} %)"

        v = self.p.video
        specs = (
            ("white_clip", "y_above_pct", "y_max", max, s.y_tolerance[1], v.y_tolerance_high_pct,
             f"Y au-dessus de {number(v.y_tolerance_high_pct, 0)} %"),
            ("black_crush", "y_below_pct", "y_min", min, s.y_tolerance[0], v.y_tolerance_low_pct,
             f"Y sous {number(v.y_tolerance_low_pct, 0)} %"),
            ("gamut", "rgb_out_pct", None, None, None, None,
             f"R, V ou B hors [{number(v.rgb_min_pct, 0)} %, {number(v.rgb_max_pct, 0)} %]"),
        )
        for event_type, column, extreme, pick, bound, bound_pct, what in specs:
            values = self.v[column]
            hit = (values >= area) & ~self.bars
            for a, b in self.aggregate(event_type, hit):
                idx = np.flatnonzero(hit[a: b + 1]) + a
                worst_frame = int(idx[np.argmax(values[idx])])
                area_max = float(values[idx].max())
                if extreme is None:
                    worst, value, limit = area_max, _pct(area_max), f"surface < {_pct(area, 0)}"
                else:
                    worst = float(pick(self.v[extreme][idx]))
                    value = code(worst)
                    limit = f"{bound} ({number(bound_pct, 0)} %), surface < {_pct(area, 0)}"
                self.add(type=event_type, title=f"{what} sur {_pct(area_max)} de l'image", source="measure",
                         scope="range", frame_start=a, frame_end=b, value_text=value, threshold_text=limit,
                         worst_value=worst, worst_frame=worst_frame, threshold=None if bound is None else float(bound),
                         area_pct_max=area_max,
                         detail=f"{len(idx)} image(s) hors tolérance sur {b - a + 1}")

    # --- audio ----------------------------------------------------------------------------

    def _block_range(self, a: int, b: int) -> tuple[int, int]:
        st = self.m.audio.settings
        first = block_frames(a, st.block_samples, st.sample_rate, self.fps, self.frames)[0]
        last = block_frames(b, st.block_samples, st.sample_rate, self.fps, self.frames)[1]
        return first, last

    def _block_events(self, event_type: str, mask: np.ndarray, values: np.ndarray, worst_is_max: bool,
                      min_seconds: float | None = None) -> list[tuple[int, int, float, int, int]]:
        """Runs of blocks -> merged frame ranges: (first frame, last frame, worst value, worst frame, blocks)."""
        block = self.m.audio.settings.block_samples / self.m.audio.settings.sample_rate
        runs = [(a, b) for a, b in detect.runs(mask)
                if min_seconds is None or (b - a + 1) * block > min_seconds]
        frame_runs = {self._block_range(a, b): (a, b) for a, b in runs}
        out = []
        for fa, fb in self.aggregate(event_type, self._frames_mask(frame_runs)):
            blocks = [r for fr, r in frame_runs.items() if fa <= fr[0] and fr[1] <= fb]
            idx = np.concatenate([np.arange(a, b + 1) for a, b in blocks])
            k = int(idx[np.argmax(values[idx])] if worst_is_max else idx[np.argmin(values[idx])])
            worst_frame = self._block_range(k, k)[0]
            out.append((fa, fb, float(values[k]), worst_frame, len(idx)))
        return out

    def _frames_mask(self, ranges: Iterable[tuple[int, int]]) -> np.ndarray:
        mask = np.zeros(self.frames, dtype=bool)
        for a, b in ranges:
            mask[a: b + 1] = True
        return mask

    def _program_blocks(self, count: int) -> np.ndarray:
        prog = self.m.audio.program
        size = self.m.audio.settings.block_samples
        k = np.arange(count)
        return (k * size < prog.sample_end) & ((k + 1) * size > prog.sample_start)

    def loudness_rules(self) -> tuple[str, LoudnessRules]:
        loud = self.p.audio.loudness
        prog = self.m.audio.program
        seconds = (prog.sample_end - prog.sample_start) / self.m.audio.settings.sample_rate
        if loud.short is not None and seconds < loud.long_program_min_seconds:
            return "short", loud.short
        return "long", loud.long

    def audio(self) -> None:
        if self.m.audio is None:
            return
        a = self.p.audio
        prog = self.m.audio.program
        prog_range = dict(frame_start=prog.frame_start, frame_end=prog.frame_end)
        silent_tracks = self.silent_tracks()
        kind, rs = self.loudness_rules()
        exempt = set(a.loudness_exempt_groups or [])
        for name, g in self.m.audio.groups.items():
            blocks = self.blocks.get(name)
            label = f"{name} ({tracks_text(g.group.tracks)})"
            all_silent = all(t in silent_tracks for t in g.group.tracks)
            # Loudness.
            if g.integrated_lufs is None:
                if not all_silent:
                    self.add(type="audio_loudness", title=f"Loudness intégré {name}", source="measure", scope="file",
                             **prog_range, value_text="aucun bloc au-dessus de -70 LUFS",
                             threshold_text=f"{number(rs.integrated_lufs)} ± {number(rs.integrated_tolerance_lu)} LU",
                             threshold=rs.integrated_lufs, group=label)
            elif abs(g.integrated_lufs - rs.integrated_lufs) > rs.integrated_tolerance_lu:
                self.add(type="audio_loudness", title=f"Loudness intégré {name}", source="measure", scope="file",
                         **prog_range, value_text=_db(g.integrated_lufs, "LUFS"),
                         threshold_text=f"{number(rs.integrated_lufs)} ± {number(rs.integrated_tolerance_lu)} LU",
                         worst_value=g.integrated_lufs, threshold=rs.integrated_lufs, group=label,
                         detail=f"règles programme {'court' if kind == 'short' else 'long'}")
            if rs.lra_max_lu is not None and g.lra_lu is not None and g.lra_lu > rs.lra_max_lu:
                self.add(type="audio_lra", title=f"LRA {name}", source="measure", scope="file", **prog_range,
                         value_text=_db(g.lra_lu, "LU"), threshold_text=f"≤ {number(rs.lra_max_lu)} LU",
                         worst_value=g.lra_lu, threshold=rs.lra_max_lu, group=label)
            if blocks is None:
                continue
            in_prog = self._program_blocks(blocks.t.size)
            self._true_peak(name, label, blocks, in_prog)
            self._short_term(name, label, blocks, in_prog, rs, kind, name in exempt)
            if not all_silent:
                self._silence(name, label, blocks, in_prog)
            if len(g.group.tracks) == 2:
                self._phase(name, label, blocks, in_prog)
                if g.group.layout == "dual_mono" and a.dual_mono_must_be_identical:
                    self._dual_mono(name, label, blocks, in_prog)
        for track in sorted(silent_tracks):
            level = next(t for t in self.m.audio.tracks if t.track == track)
            group = next((g.name for g in self.probe.audio_map.groups if track in g.tracks), "hors mapping")
            self.add(type="audio_silent_track", title=f"Piste {track} sans contenu", source="measure", scope="file",
                     **prog_range, value_text=_db(level.peak_dbfs, "dBFS (crête)"),
                     threshold_text=f"crête ≥ {number(a.silent_track_dbfs)} dBFS", worst_value=level.peak_dbfs,
                     threshold=a.silent_track_dbfs, group=f"piste {track} ({group})")

    def silent_tracks(self) -> set[int]:
        a = self.p.audio
        if not a.no_silent_tracks:
            return set()
        limit = require(self.p, "audio.silent_track_dbfs", "le contrôle des pistes silencieuses")
        return {t.track for t in self.m.audio.tracks if t.peak_dbfs is None or t.peak_dbfs < limit}

    def _true_peak(self, name: str, label: str, b: GroupBlocks, in_prog: np.ndarray) -> None:
        limit = self.p.audio.true_peak_max_dbtp
        tp = b.tp.max(axis=1)
        for fa, fb, worst, wf, _ in self._block_events("audio_true_peak", (tp > limit) & in_prog, tp, True):
            self.add(type="audio_true_peak", title=f"True peak {name}", source="measure", scope="range",
                     frame_start=fa, frame_end=fb, value_text=_db(worst, "dBTP"),
                     threshold_text=f"≤ {number(limit)} dBTP", worst_value=worst, worst_frame=wf, threshold=limit,
                     group=label)

    def _short_term(self, name: str, label: str, b: GroupBlocks, in_prog: np.ndarray, rs: LoudnessRules,
                    kind: str, exempt: bool) -> None:
        limits = []
        if kind == "long" and rs.short_term_dialogue_excursion_lu is not None and not exempt:
            limits.append((rs.integrated_lufs + rs.short_term_dialogue_excursion_lu,
                           f"cible + {number(rs.short_term_dialogue_excursion_lu)} LU"))
        if kind == "short":
            if rs.short_term_max_lufs is not None:
                limits.append((rs.short_term_max_lufs, "maximum absolu"))
            if rs.short_term_excursion_above_lu is not None:
                limits.append((rs.integrated_lufs + rs.short_term_excursion_above_lu,
                               f"cible + {number(rs.short_term_excursion_above_lu)} LU"))
        if not limits:
            return
        limit, why = min(limits)
        st = self.m.audio.settings
        window = 30  # a short-term value covers 3 s: count it once its window lies in the programme
        k = np.arange(b.t.size)
        full = (k + 1 - window) * st.block_samples >= self.m.audio.program.sample_start
        with np.errstate(invalid="ignore"):
            hit = (np.nan_to_num(b.s, nan=-np.inf) > limit) & in_prog & full
        s = np.nan_to_num(b.s, nan=-np.inf)
        for fa, fb, worst, wf, _ in self._block_events("audio_short_term_excursion", hit, s, True):
            self.add(type="audio_short_term_excursion", title=f"Loudness short term {name}", source="measure",
                     scope="range", frame_start=fa, frame_end=fb, value_text=_db(worst, "LUFS"),
                     threshold_text=f"≤ {number(limit)} LUFS ({why})", worst_value=worst, worst_frame=wf,
                     threshold=limit, group=label,
                     detail="excursion vers le haut seulement : le dialogue n'est pas détecté automatiquement"
                     if kind == "long" else "")

    def _silence(self, name: str, label: str, b: GroupBlocks, in_prog: np.ndarray) -> None:
        a = self.p.audio
        max_seconds = require(self.p, "audio.silence_max_seconds", "le contrôle des silences")
        peak = b.peak.max(axis=1)
        hit = (peak < a.silence_dbfs) & in_prog
        for fa, fb, worst, wf, n in self._block_events("audio_silence", hit, peak, True, max_seconds):
            self.add(type="audio_silence", title=f"Silence {name}", source="measure", scope="range",
                     frame_start=fa, frame_end=fb, value_text=f"crête {_db(worst, 'dBFS')}",
                     threshold_text=f"silence < {number(a.silence_dbfs)} dBFS pendant ≤ {number(max_seconds)} s",
                     worst_value=None if worst == -math.inf else worst, worst_frame=wf, threshold=a.silence_dbfs,
                     group=label, detail=f"{number(n * self.m.audio.settings.block_samples / self.m.audio.settings.sample_rate, 1)} s de silence")

    def _phase(self, name: str, label: str, b: GroupBlocks, in_prog: np.ndarray) -> None:
        a = self.p.audio
        min_seconds = require(self.p, "audio.phase_min_seconds", "le contrôle de phase")
        corr = np.nan_to_num(b.corr, nan=np.inf)
        hit = (corr < a.phase_min_correlation) & in_prog
        for fa, fb, worst, wf, _ in self._block_events("audio_phase", hit, corr, False, min_seconds):
            self.add(type="audio_phase", title=f"Opposition de phase {name}", source="measure", scope="range",
                     frame_start=fa, frame_end=fb, value_text=f"corrélation {number(worst, 2)}",
                     threshold_text=f"≥ {number(a.phase_min_correlation, 2)} (plus de {number(min_seconds)} s)",
                     worst_value=worst, worst_frame=wf, threshold=a.phase_min_correlation, group=label)

    def _dual_mono(self, name: str, label: str, b: GroupBlocks, in_prog: np.ndarray) -> None:
        hit = (b.diff > -np.inf) & in_prog
        for fa, fb, worst, wf, _ in self._block_events("audio_dual_mono_mismatch", hit, b.diff, True):
            self.add(type="audio_dual_mono_mismatch", title=f"Double mono {name} non identique", source="measure",
                     scope="range", frame_start=fa, frame_end=fb, value_text=f"écart crête {_db(worst, 'dBFS')}",
                     threshold_text="pistes identiques", worst_value=worst, worst_frame=wf, group=label)

    # --- severity, verdict ----------------------------------------------------------------

    def possible_types(self) -> set[str]:
        """Event types this analysis can produce, whatever the content: their severity chain must exist."""
        groups = [g.group for g in self.m.audio.groups.values()] if self.m.audio is not None else []
        types = severity_types(self.p, groups)
        return types | {c.type for c in self.probe.checks} | {c.type for c in self.st.checks}

    def severity(self, d: Draft) -> tuple[Severity, str]:
        """(severity, source of the rule that gave it)."""
        if d.severity is not None:
            return d.severity, "format.unknown_color_tags_severity"
        env = {
            "duration_frames": d.frame_end - d.frame_start + 1, "worst_value": d.worst_value,
            "area_pct_max": d.area_pct_max, "threshold": d.threshold, "frame_start": d.frame_start,
            "frame_end": d.frame_end,
        }
        assert set(env) == set(EVENT_FIELDS)
        defined = {k: v for k, v in env.items() if v is not None}
        for rule in self.p.rules.severity[d.type]:
            if rule.else_ is not None:
                return rule.else_, rule.source
            try:
                if expr.evaluate(rule.if_, defined):
                    return rule.then, rule.source
            except expr.ExpressionError:
                missing = [k for k in env if k not in defined and re.search(rf"\b{k}\b", rule.if_)]
                raise RulesError(
                    f"rules.severity.{d.type} : la condition « {rule.if_} » utilise "
                    f"{', '.join(missing) or 'un nom inconnu'}, non défini pour l'anomalie « {d.title} »"
                ) from None
        raise AssertionError("severity chains end with else")  # checked when the profile is loaded

    def run(self) -> tuple[list[Event], Verdict]:
        missing = sorted(t for t in self.possible_types() if t not in self.p.rules.severity)
        if missing:
            raise RulesError(
                "le profil n'a pas de gravité pour : " + ", ".join(f"rules.severity.{t}" for t in missing)
            )
        self.probe_checks()
        self.integrity()
        self.structure_checks()
        self.structure_findings()
        self.levels()
        self.audio()

        drafts = sorted(self.drafts, key=lambda d: (d.scope != "file", d.frame_start, d.frame_end, d.type, d.title))
        rated = [(d, *self.severity(d)) for d in drafts]
        events = [
            Event(id=i, type=d.type, severity=severity, severity_source=rule_source, title=d.title, source=d.source,
                  scope=d.scope,
                  frame_start=d.frame_start, frame_end=d.frame_end, tc_start=self.clock.tc(d.frame_start),
                  tc_end=self.clock.tc(d.frame_end), duration_frames=d.frame_end - d.frame_start + 1,
                  worst_value=d.worst_value, worst_frame=d.worst_frame, threshold=d.threshold,
                  area_pct_max=d.area_pct_max, value_text=d.value_text, threshold_text=d.threshold_text,
                  group=d.group, detail=d.detail, occurrences=d.occurrences)
            for i, (d, severity, rule_source) in enumerate(rated, start=1)
        ]
        return events, self.verdict(events)

    def verdict(self, events: list[Event]) -> Verdict:
        counts = {s: sum(e.severity == s for e in events) for s in SEVERITY_ORDER}
        max_major = self.p.rules.max_major
        reasons = []
        if counts["blocking"]:
            reasons.append(f"{counts['blocking']} anomalie(s) bloquante(s)")
        if counts["major"] > max_major:
            reasons.append(f"{counts['major']} anomalie(s) majeure(s), {max_major} tolérée(s)")
        score = float(expr.evaluate(self.p.rules.score_formula, counts))
        return Verdict(
            tool_version=__version__, profile=self.probe.profile, source_sha256=self.m.source.sha256,
            status="NON-CONFORME" if reasons else "CONFORME", score=round(min(max(score, 0.0), 100.0), 1),
            score_formula=self.p.rules.score_formula, counts=counts, max_major=max_major, reasons=reasons,
        )


def run(workdir: Path, profile: Profile) -> tuple[Events, Verdict]:
    probe = wd.load(workdir, wd.PROBE, ProbeResult, "analyze")
    m = wd.load(workdir, wd.MEASUREMENTS, Measurements, "analyze")
    structure = wd.load(workdir, wd.STRUCTURE, Structure, "structure")
    for name in (wd.EVENTS, wd.VERDICT):
        (workdir / name).unlink(missing_ok=True)
    engine = Engine(probe, m, structure, profile, load_video(workdir, m), load_audio(workdir, m))
    events, verdict = engine.run()
    result = Events(tool_version=__version__, profile=probe.profile, source_sha256=m.source.sha256, events=events)
    jsonio.write(workdir / wd.EVENTS, result)
    jsonio.write(workdir / wd.VERDICT, verdict)
    return result, verdict
