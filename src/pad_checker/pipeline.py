"""Steps after the measurements: structure -> rules -> report, and their reruns.

``analyze`` runs everything; ``rerun`` (and ``report``) start again from the JSON already in the
analysis directory, without measuring again. The profile used is copied into the directory
(``profile.yaml``) so that a rerun applies the same rules. A rerun with another profile is
accepted only if that profile leaves every measurement setting unchanged (thresholds converted
to code values, prefilter, flash delta, programme range, audio groups): otherwise the
measurements would not mean what the new profile says, and the analysis has to be redone.
"""

from __future__ import annotations

import datetime as dt
import shutil
from collections.abc import Callable
from pathlib import Path

from pad_checker import jsonio, report, structure, workdir as wd
from pad_checker.measure.models import Measurements
from pad_checker.measure.program import program_range
from pad_checker.measure.series import load_video
from pad_checker.measure.video import VideoLimits
from pad_checker.probe import probe_file
from pad_checker.probe.models import ProbeResult
from pad_checker.probe.probe import sha256_file
from pad_checker.rules import engine
from pad_checker.rules.profile import AudioGroup, Profile, ProfileValueError, load_profile, require
from pad_checker.workdir import Rerun, RunInfo, Step

STEPS: tuple[Step, ...] = ("structure", "rules", "report")
Progress = Callable[[str], None]


class PipelineError(Exception):
    """A step cannot run. The message is user-facing (French)."""


def now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def start_run(workdir: Path, profile_path: Path, command: str) -> None:
    workdir.mkdir(parents=True, exist_ok=True)
    copy = workdir / wd.PROFILE
    if not copy.exists() or not copy.samefile(profile_path):
        shutil.copyfile(profile_path, copy)
    jsonio.write(workdir / wd.RUN, RunInfo(analyzed_at=now(), command=command, profile_file=str(profile_path)))


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
    needs += [("audio.silence_max_seconds", "les silences"), ("audio.phase_min_seconds", "la phase")]
    if profile.audio.no_silent_tracks:
        needs.append(("audio.silent_track_dbfs", "les pistes silencieuses"))
    problems = []
    for dotted, purpose in needs:
        try:
            require(profile, dotted, purpose)
        except ProfileValueError as exc:
            problems.append(str(exc))

    problems += [f"le profil n'a pas de gravité pour « rules.severity.{t} »"
                 for t in sorted(engine.severity_types(profile, groups)) if t not in profile.rules.severity]
    return problems


def run_steps(workdir: Path, profile: Profile, first: Step = "structure", thumbnails: bool = False,
              progress: Progress | None = None) -> None:
    progress = progress or (lambda _msg: None)
    todo = STEPS[STEPS.index(first):]
    if "structure" in todo:
        progress("Structure : mire, noirs, timecode, images figées, PSE, format d'image")
        structure.run(workdir, profile, progress)
    if "rules" in todo:
        progress("Règles : événements, gravité, verdict")
        engine.run(workdir, profile)
    if "report" in todo:
        progress("Rapport")
        report.run(workdir, profile, thumbnails=thumbnails, progress=progress)


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


def rerun(workdir: Path, first: Step, profile_path: Path | None, command: str, thumbnails: bool = False,
          progress: Progress | None = None) -> None:
    probe = wd.load(workdir, wd.PROBE, ProbeResult, "analyze")
    m = wd.load(workdir, wd.MEASUREMENTS, Measurements, "analyze")
    stored = workdir / wd.PROFILE
    if profile_path is None:
        if not stored.is_file():
            raise PipelineError(f"{wd.PROFILE} absent de {workdir} : préciser le profil avec --profile")
        profile_path = stored
    profile = load_profile(profile_path)
    if sha256_file(profile_path) != probe.profile.sha256:
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
    # Recorded first, so that the report written by this rerun mentions it.
    run_file = workdir / wd.RUN
    info = jsonio.read(run_file, RunInfo) if run_file.is_file() else RunInfo(
        analyzed_at="inconnue", command="inconnue", profile_file=str(profile_path))
    info.reruns.append(Rerun(at=now(), command=command, from_step=first, profile_file=str(profile_path)))
    jsonio.write(run_file, info)
    run_steps(workdir, profile, first, thumbnails, progress)
