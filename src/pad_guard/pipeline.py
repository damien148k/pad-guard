"""Steps after the measurements: structure -> rules -> report, and their reruns.

``analyze`` runs everything; ``rerun`` (and ``report``) start again from the JSON already in the
analysis directory, without measuring again. The effective profile used (profile + inherited
norms) is written into the directory (``effective_profile.json``, next to a byte copy of the
profile file, ``profile.yaml``) so that a rerun applies the same rules even if a norm file has
changed since. A rerun with another profile is accepted only if that profile leaves every
measurement setting unchanged (thresholds converted to code values, prefilter, flash delta,
scan detection, programme range, audio groups): otherwise the measurements would not mean what
the new profile says, and the analysis has to be redone.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import shutil
from collections.abc import Callable
from pathlib import Path

from pad_guard import jsonio, report, structure, workdir as wd
from pad_guard.measure.models import Measurements
from pad_guard.measure.program import program_range
from pad_guard.measure.series import load_video
from pad_guard.measure.video import VideoLimits
from pad_guard.probe import probe_file
from pad_guard.probe.models import ProbeResult
from pad_guard.profiles import ResolvedProfile, from_json, resolve_profile
from pad_guard.rules import engine
from pad_guard.rules.profile import AudioGroup, Profile, ProfileError, ProfileValueError, require
from pad_guard.workdir import Rerun, RunInfo, Step

STEPS: tuple[Step, ...] = ("structure", "rules", "report")
Progress = Callable[[str], None]


class PipelineError(Exception):
    """A step cannot run. The message is user-facing (French)."""


def now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def write_effective(workdir: Path, resolved: ResolvedProfile) -> None:
    (workdir / wd.EFFECTIVE_PROFILE).write_text(resolved.dumps(), encoding="utf-8", newline="\n")


def start_run(workdir: Path, profile_path: Path, command: str, resolved: ResolvedProfile) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    copy = workdir / wd.PROFILE
    if not copy.exists() or not copy.samefile(profile_path):
        shutil.copyfile(profile_path, copy)
    write_effective(workdir, resolved)
    jsonio.write(workdir / wd.RUN, RunInfo(analyzed_at=now(), command=command, profile_file=str(profile_path)))


def finish_run(workdir: Path) -> None:
    """Record in run.json the end of ``analyze`` (the interface shows how long it took)."""
    run_file = workdir / wd.RUN
    if run_file.is_file():
        info = jsonio.read(run_file, RunInfo)
        info.finished_at = now()
        jsonio.write(run_file, info)


def preflight(profile: Profile, groups: list[AudioGroup]) -> list[str]:
    """Profile values and severity chains the analysis will need, checked before measuring (French).

    The steps check them again when they use them; this only avoids discovering a missing value
    after a long measurement pass.
    """
    s = profile.structure
    needs: list[tuple[str, str]] = []
    if s.bars.required:
        needs += [(f"structure.bars.{k}", "la mire de tête") for k in
                  ("tolerance", "pattern", "start_tc", "min_seconds", "tone_hz", "tone_dbfs", "tone_tolerance_db")]
    elif s.bars.forbidden:
        needs.append(("structure.bars.tolerance", "la recherche de mire"))
    if s.leaders == "classic":
        needs += [("structure.black.head_min_seconds", "le noir de tête"), ("structure.black.tail_min_seconds", "le noir de queue")]
    else:
        needs += [("structure.black.head_max_seconds", "le noir de tête"), ("structure.black.tail_max_seconds", "le noir de queue")]
    if profile.format.letterbox is not None and profile.format.letterbox.check:
        needs.append(("format.letterbox.tolerance_lines", "le format d'image"))
    needs += [("audio.silence_max_seconds", "les silences"), ("audio.phase_min_seconds", "la phase"),
              ("video.scan_detection", "la détection du balayage")]
    if profile.format.delivery is not None:
        needs += [("format.delivery.scan", "la comparaison au format de livraison"),
                  ("format.delivery.fps", "la comparaison au format de livraison")]
    if profile.audio.no_silent_tracks:
        needs.append(("audio.silent_track_dbfs", "les pistes silencieuses"))
    problems = []
    for dotted, purpose in needs:
        try:
            require(profile, dotted, purpose)
        except ProfileValueError as exc:
            problems.append(str(exc))

    params = profile.rules.params.model_dump()
    for name, chain in sorted(profile.rules.severity.items()):
        for rule in chain:
            used = [k for k, v in params.items() if v is None and rule.if_ and re.search(rf"\b{k}\b", rule.if_)]
            for param in sorted(used):
                problems.append(f"rules.params.{param} : valeur absente du profil effectif, nécessaire pour "
                                f"rules.severity.{name} (« {rule.if_} »)")
    problems += [f"le profil n'a pas de gravité pour « rules.severity.{t} »"
                 for t in sorted(engine.severity_types(profile, groups)) if profile.rules.chain(t) is None]
    return problems


def run_steps(workdir: Path, profile: Profile, first: Step = "structure", thumbnails: bool | None = None,
              progress: Progress | None = None, ai: report.ai.Options | None = None,
              on_step: Callable[[Step], None] | None = None) -> None:
    """``on_step`` is called with the name of each step before it starts (--progress-json)."""
    progress = progress or (lambda _msg: None)
    on_step = on_step or (lambda _step: None)
    todo = STEPS[STEPS.index(first):]
    if "structure" in todo:
        on_step("structure")
        progress("Structure : mire, noirs, timecode, images figées, PSE, format d'image")
        structure.run(workdir, profile, progress)
    if "rules" in todo:
        on_step("rules")
        progress("Règles : événements, gravité, verdict")
        engine.run(workdir, profile)
    if "report" in todo:
        on_step("report")
        progress("Rapport")
        report.run(workdir, profile, thumbnails=thumbnails, progress=progress, ai=ai)


def measurement_differences(workdir: Path, probe: ProbeResult, m: Measurements, profile: Profile) -> list[str]:
    """Measurement settings that ``profile`` would change (French). Empty: the measurements stand."""
    out = []
    limits = VideoLimits.from_profile(profile)
    s = m.video_settings
    for name, new, old in (
        ("Y légal (codes 10 bits)", limits.y_legal, tuple(s.y_legal)),
        ("Y toléré (codes 10 bits)", limits.y_tolerance, tuple(s.y_tolerance)),
        ("RVB toléré (codes 10 bits)", limits.rgb, tuple(s.rgb)),
        ("préfiltre (prefilter_taps)", limits.prefilter_taps, s.prefilter_taps),
        ("matrice", limits.matrix, s.matrix),
        ("seuil de flash (structure.pse.flash_min_delta_pct)", limits.flash_delta_pct, s.flash_delta_pct),
    ):
        if new != old:
            out.append(f"{name} : {old} → {new}")
    if profile.video.scan_detection != m.scan.settings:
        out.append("détection du balayage (video.scan_detection)")
    if probe.audio_map.source == "profile" and probe.audio_map.groups != profile.audio.groups:
        out.append("groupes audio (audio.groups)")
    if m.audio is not None:
        video = load_video(workdir, m)
        y_p99 = [int(x) for x in video["y_p99"]]
        new = program_range(probe, profile, y_p99, video.frames, m.audio.settings.sample_rate)
        if new != m.audio.program:
            out.append(f"plage programme audio : images {m.audio.program.frame_start}-{m.audio.program.frame_end} "
                       f"→ {new.frame_start}-{new.frame_end}")
    return out


def rerun(workdir: Path, first: Step, profile_path: Path | None, command: str, thumbnails: bool | None = None,
          progress: Progress | None = None, ai: report.ai.Options | None = None,
          on_step: Callable[[Step], None] | None = None) -> None:
    probe = wd.load(workdir, wd.PROBE, ProbeResult, "analyze")
    m = wd.load(workdir, wd.MEASUREMENTS, Measurements, "analyze")
    stored = workdir / wd.PROFILE
    effective = workdir / wd.EFFECTIVE_PROFILE
    if profile_path is None and effective.is_file():
        # The profile of the analysis, as it was resolved then (norm files may have changed since).
        try:
            resolved = from_json(json.loads(effective.read_text(encoding="utf-8")), effective)
        except json.JSONDecodeError as exc:
            raise ProfileError(effective, [f"JSON invalide ({exc}) : relancer « analyze »"]) from None
        profile_path = stored
    else:
        if profile_path is None:
            if not stored.is_file():
                raise PipelineError(f"{wd.PROFILE} absent de {workdir} : préciser le profil avec --profile")
            profile_path = stored
        resolved = resolve_profile(profile_path)
    profile = resolved.profile
    if resolved.fingerprint != probe.profile.effective_sha256:
        diffs = measurement_differences(workdir, probe, m, profile)
        if diffs:
            raise PipelineError(
                "ce profil change des paramètres de mesure, il faut relancer « analyze » : " + " ; ".join(diffs)
            )
        # Same measurements, other rules: the format checks are evaluated again (no new hash).
        source = Path(probe.source.path)
        if not source.is_file():
            raise PipelineError(f"fichier source introuvable : {source} (nécessaire pour changer de profil)")
        probe = probe_file(source, profile, profile_path, probe.audio_map if probe.audio_map.source == "command_line"
                           else None, known=probe.source)
        if not probe.accepted:
            raise PipelineError("fichier refusé par ce profil : " + " ".join(probe.refusal_reasons))
        jsonio.write(workdir / wd.PROBE, probe)
        if not stored.exists() or not stored.samefile(profile_path):
            shutil.copyfile(profile_path, stored)
        first = "structure"
    write_effective(workdir, resolved)
    # Recorded first, so that the report written by this rerun mentions it.
    run_file = workdir / wd.RUN
    info = jsonio.read(run_file, RunInfo) if run_file.is_file() else RunInfo(
        analyzed_at="inconnue", command="inconnue", profile_file=str(profile_path))
    info.reruns.append(Rerun(at=now(), command=command, from_step=first, profile_file=str(profile_path)))
    jsonio.write(run_file, info)
    run_steps(workdir, profile, first, thumbnails, progress, ai, on_step)
