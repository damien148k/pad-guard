"""Command-line entry point: ``pad-checker``."""

from __future__ import annotations

import subprocess
import time
from enum import Enum
from fractions import Fraction
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeRemainingColumn
from rich.table import Table

from pad_checker import __version__, audio_map as amap, jsonio, measure, pipeline, workdir as wd
from pad_checker.decode.video import DecoderOpenError, VideoDecoder
from pad_checker.labels import SEVERITY_LABELS, SEVERITY_ORDER
from pad_checker.measure.models import Measurements
from pad_checker.probe import ProbeError, probe_file
from pad_checker.probe.models import ProbeResult
from pad_checker.report import ReportError
from pad_checker.rules.engine import RulesError
from pad_checker.rules.models import Verdict
from pad_checker.rules.profile import Profile, ProfileError, ProfileValueError, load_profile, null_fields
from pad_checker.structure import StructureError
from pad_checker.structure.bars import BarsError

app = typer.Typer(
    help="Contrôle qualité de fichiers Prêt à Diffuser (ProRes 422 HQ / DNxHR HQX).",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)

EXIT_USAGE = 1
EXIT_REFUSED = 2
EXIT_NOT_IMPLEMENTED = 3
EXIT_NON_CONFORME = 4  # the analysis ran to the end and the verdict is NON-CONFORME

_STATUS = {"ok": "[green]OK[/green]", "fail": "[red]ÉCHEC[/red]", "unknown": "[yellow]?[/yellow]"}


class LlmBackend(str, Enum):
    none = "none"
    ollama = "ollama"


class StepName(str, Enum):
    structure = "structure"
    rules = "rules"
    report = "report"


def _version(value: bool) -> None:
    if value:
        console.print(f"pad-checker {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(False, "--version", callback=_version, is_eager=True, help="Affiche la version."),
) -> None:
    pass


@app.command()
def analyze(
    file: Path = typer.Argument(..., help="Fichier master (.mov ou .mxf)."),
    profile: Path = typer.Option(..., "--profile", "-p", help="Profil de chaîne (YAML)."),
    out: Path = typer.Option(..., "--out", "-o", help="Dossier de travail et de sortie."),
    audio_map: str | None = typer.Option(
        None, "--audio-map",
        help="Groupes de pistes audio pour cette analyse, ex. « VO:1-2,VF:3-4 » (remplace audio.groups du profil).",
    ),
    llm: LlmBackend = typer.Option(LlmBackend.none, "--llm", help="Synthèse rédigée par un LLM local."),
    thumbnails: bool = typer.Option(False, "--thumbnails", help="Extraire une vignette par événement."),
    quick: bool = typer.Option(False, "--quick", help="Aperçu rapide (1 image sur 25), sans verdict."),
    benchmark: bool = typer.Option(False, "--benchmark", help="Mesure la vitesse de décodage seule."),
    workers: int = typer.Option(
        0, "--workers", min=0, help="Processus de mesure vidéo (0 = automatique). Sans effet sur les résultats.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Affiche la progression détaillée."),
) -> None:
    """Analyse un fichier et produit mesures, événements, verdict et rapport."""
    prof = _load_profile_or_exit(profile)
    mapping = _audio_map_or_exit(audio_map, prof)
    for flag, name in ((quick, "--quick"), (llm != LlmBackend.none, "--llm")):
        if flag:
            err_console.print(f"[yellow]{name} : non implémenté, option ignorée.[/yellow]")
    problems = pipeline.preflight(prof, mapping.groups)
    if problems:
        err_console.print(f"[red]Profil incomplet pour cette analyse : {profile}[/red]")
        for msg in problems:
            err_console.print(f"  - {msg}")
        raise typer.Exit(EXIT_USAGE)
    command = _command("analyze", str(file), "--profile", str(profile), "--out", str(out),
                       *(("--audio-map", audio_map) if audio_map else ()), *(("--thumbnails",) if thumbnails else ()),
                       *((f"--workers", str(workers)) if workers else ()))

    try:
        result = probe_file(file, prof, profile, mapping)
    except ProbeError as exc:
        err_console.print(f"[red]Fichier refusé : {exc}[/red]")
        raise typer.Exit(EXIT_REFUSED) from None
    if not benchmark:
        pipeline.start_run(out, profile, command)
    jsonio.write(out / wd.PROBE, result)
    _print_probe(result)
    console.print(f"probe.json écrit dans {out}")

    if not result.accepted:
        err_console.print("[red]Fichier refusé : ce n'est pas un master pris en charge.[/red]")
        for reason in result.refusal_reasons:
            err_console.print(f"  - {reason}")
        raise typer.Exit(EXIT_REFUSED)

    if benchmark:
        _benchmark(file, result)
        return

    measurements = _measure(result, prof, out, workers)
    _print_measurements(measurements, out)
    _steps(lambda: pipeline.run_steps(out, prof, "structure", thumbnails, _progress(verbose)))
    _finish(out)


@app.command()
def rerun(
    workdir: Path = typer.Argument(..., help="Dossier produit par « analyze »."),
    from_step: StepName = typer.Option(
        StepName.structure, "--from", help="Première étape à relancer : structure, rules ou report.",
    ),
    profile: Path | None = typer.Option(
        None, "--profile", "-p",
        help="Autre profil (par défaut : la copie profile.yaml du dossier). Refusé s'il change les mesures.",
    ),
    thumbnails: bool = typer.Option(False, "--thumbnails", help="Extraire une vignette par événement image."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Affiche la progression détaillée."),
) -> None:
    """Relance structure, règles et rapport à partir des JSON existants, sans refaire les mesures."""
    if profile is not None:
        prof = _load_profile_or_exit(profile)
        problems = pipeline.preflight(prof, prof.audio.groups)
        if problems:
            err_console.print(f"[red]Profil incomplet pour cette analyse : {profile}[/red]")
            for msg in problems:
                err_console.print(f"  - {msg}")
            raise typer.Exit(EXIT_USAGE)
    command = _command("rerun", str(workdir), "--from", from_step.value, *(("--profile", str(profile)) if profile else ()),
                       *(("--thumbnails",) if thumbnails else ()))
    _steps(lambda: pipeline.rerun(workdir, from_step.value, profile, command, thumbnails, _progress(verbose)))
    _finish(workdir)


@app.command()
def report(
    workdir: Path = typer.Argument(..., help="Dossier produit par « analyze »."),
    thumbnails: bool = typer.Option(False, "--thumbnails", help="Extraire une vignette par événement image."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Affiche la progression détaillée."),
) -> None:
    """Régénère le rapport à partir des JSON d'un dossier d'analyse (= rerun --from report)."""
    command = _command("report", str(workdir), *(("--thumbnails",) if thumbnails else ()))
    _steps(lambda: pipeline.rerun(workdir, "report", None, command, thumbnails, _progress(verbose)))
    _finish(workdir)


def _command(*args: str) -> str:
    return subprocess.list2cmdline(["pad-checker", *args])


def _progress(verbose: bool):
    return (lambda msg: err_console.print(f"[dim]{msg}[/dim]")) if verbose else None


_STEP_ERRORS = (
    wd.WorkdirError, pipeline.PipelineError, StructureError, RulesError, ReportError, ProfileValueError, BarsError,
)


def _steps(action) -> None:
    try:
        action()
    except ProfileError as exc:
        err_console.print(f"[red]Profil invalide : {exc.path}[/red]")
        for msg in exc.messages:
            err_console.print(f"  - {msg}")
        raise typer.Exit(EXIT_USAGE) from None
    except _STEP_ERRORS as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(EXIT_USAGE) from None
    except DecoderOpenError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(EXIT_REFUSED) from None


def _finish(out: Path) -> None:
    verdict = jsonio.read(out / wd.VERDICT, Verdict)
    colour = "green" if verdict.status == "CONFORME" else "red"
    counts = ", ".join(f"{verdict.counts[s]} {SEVERITY_LABELS[s]}" for s in SEVERITY_ORDER)
    console.print(f"[bold {colour}]{verdict.status}[/bold {colour}] — score {verdict.score:g}/100 ({counts})")
    for reason in verdict.reasons:
        console.print(f"  - {reason}")
    console.print(f"Rapport : {out / wd.REPORT_MD} et {out / wd.REPORT_PDF}")
    if verdict.status != "CONFORME":
        raise typer.Exit(EXIT_NON_CONFORME)


def _load_profile_or_exit(path: Path) -> Profile:
    try:
        return load_profile(path)
    except ProfileError as exc:
        err_console.print(f"[red]Profil invalide : {exc.path}[/red]")
        for msg in exc.messages:
            err_console.print(f"  - {msg}")
        raise typer.Exit(EXIT_USAGE) from None


def _audio_map_or_exit(spec: str | None, prof: Profile) -> amap.AudioMap:
    if spec is None:
        return amap.from_profile(prof)
    try:
        return amap.parse(spec, prof)
    except amap.AudioMapError as exc:
        err_console.print(f"[red]--audio-map invalide : {exc}[/red]")
        raise typer.Exit(EXIT_USAGE) from None


def _print_probe(result: ProbeResult) -> None:
    v = result.video
    console.print(f"[bold]{Path(result.source.path).name}[/bold] — profil {result.profile.name} v{result.profile.version}")
    console.print(
        f"  {v.codec_name} {v.profile or ''}, {v.width}x{v.height}, {v.r_frame_rate} i/s, "
        f"{v.nb_frames} images, TC {result.timecode or 'absent'}, {len(result.audio_tracks)} piste(s) audio"
    )
    source = "ligne de commande" if result.audio_map.source == "command_line" else "profil"
    console.print(f"  Groupes audio ({source}) : {amap.describe(result.audio_map.groups)}")
    table = Table(title="Contrôles de format", show_lines=False)
    table.add_column("Contrôle")
    table.add_column("Attendu")
    table.add_column("Mesuré")
    table.add_column("Statut", justify="center")
    for check in result.checks:
        table.add_row(check.label, check.expected, check.actual, _STATUS[check.status])
    console.print(table)


def _measure(result: ProbeResult, prof: Profile, out: Path, workers: int) -> Measurements:
    total = result.video.nb_frames
    start = time.perf_counter()
    try:
        with Progress(
            TextColumn("Mesures"), BarColumn(), MofNCompleteColumn(), TimeRemainingColumn(),
            console=err_console, transient=True,
        ) as bar:
            task = bar.add_task("images", total=total)
            m = measure.run(result, prof, out, workers or None, progress=lambda done: bar.update(task, completed=done))
    except measure.MeasureSetupError as exc:
        err_console.print(f"[red]Profil inutilisable pour les mesures : {exc}[/red]")
        raise typer.Exit(EXIT_USAGE) from None
    except (DecoderOpenError, measure.am.AudioMeasureError) as exc:
        err_console.print(f"[red]Mesures impossibles : {exc}[/red]")
        raise typer.Exit(EXIT_REFUSED) from None
    elapsed = time.perf_counter() - start
    frames = m.video.frames
    nominal = float(Fraction(result.video.r_frame_rate))
    speed = frames / elapsed / nominal if elapsed > 0 else float("inf")
    console.print(f"Mesures : {frames} images en {elapsed:.1f} s, soit {speed:.1f}× le temps réel")
    return m


def _db(value: float | None, unit: str) -> str:
    return "silence" if value is None else f"{value:.1f} {unit}".replace(".", ",")


def _print_measurements(m: Measurements, out: Path) -> None:
    integ = m.integrity
    if integ.ok:
        console.print(f"Intégrité : [green]OK[/green] ({integ.frames_decoded}/{integ.frames_expected} images)")
    else:
        console.print(
            f"Intégrité : [red]ÉCHEC[/red] ({integ.frames_decoded}/{integ.frames_expected} images, "
            f"{len(integ.errors)} erreur(s) de décodage, {len(integ.pts_discontinuities)} discontinuité(s))"
        )
    if m.audio is not None:
        prog = m.audio.program
        where = f"{prog.tc_start} → {prog.tc_end}" if prog.tc_start else f"images {prog.frame_start} → {prog.frame_end}"
        console.print(f"Audio mesuré sur le programme : {where}")
        table = Table(title="Audio (programme)")
        for col in ("Groupe", "Pistes", "Loudness intégré", "True peak", "LRA"):
            table.add_column(col)
        for name, g in m.audio.groups.items():
            table.add_row(
                name, amap.tracks_text(g.group.tracks), _db(g.integrated_lufs, "LUFS"),
                _db(g.true_peak_dbtp, "dBTP"), "-" if g.lra_lu is None else _db(g.lra_lu, "LU"),
            )
        console.print(table)
    console.print(f"measurements.json écrit dans {out}")


def _benchmark(file: Path, result: ProbeResult) -> None:
    """Decode-only speed (ROADMAP Phase 1), with the integrity check of the decoding pass."""
    decoder = VideoDecoder(file, stream_index=result.video.stream_index, frames_expected=result.video.nb_frames)
    console.print("Décodage de toutes les images (sans mesure)...")
    start = time.perf_counter()
    try:
        frames = sum(1 for _ in decoder.frames())
    except DecoderOpenError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(EXIT_REFUSED) from None
    elapsed = time.perf_counter() - start
    fps = frames / elapsed if elapsed > 0 else float("inf")
    nominal = float(Fraction(result.video.r_frame_rate))
    console.print(
        f"[bold]{frames} images en {elapsed:.2f} s : {fps:.0f} i/s, soit {fps / nominal:.1f}× le temps réel[/bold]"
    )
    report = decoder.integrity
    if report.ok:
        console.print(f"Intégrité : [green]OK[/green] ({report.frames_decoded}/{report.frames_expected} images, aucune erreur)")
    else:
        console.print(
            f"Intégrité : [red]ÉCHEC[/red] ({report.frames_decoded}/{report.frames_expected} images, "
            f"{len(report.errors)} erreur(s), {len(report.pts_discontinuities)} discontinuité(s) de timestamp)"
        )
        for err in report.errors[:10]:
            console.print(f"  - après l'image {err.after_frame} : {err.message}")


@app.command("validate-profile")
def validate_profile(
    profile: Path = typer.Argument(..., help="Profil de chaîne (YAML)."),
) -> None:
    """Vérifie un profil de chaîne : schéma, champs inconnus, expressions de gravité."""
    prof = _load_profile_or_exit(profile)
    meta = prof.profile
    console.print(f"[green]Profil valide[/green] : {meta.name} v{meta.version} ({meta.broadcaster})")
    console.print(f"  Source : {meta.source_document}")
    unsourced = [f"rules.severity.{name}[{i}] ({rule.severity}) : {rule.source}"
                 for name, chain in prof.rules.severity.items() for i, rule in enumerate(chain)
                 if rule.severity in ("blocking", "major") and "A VERIFIER" in rule.source.upper()]
    if unsourced:
        console.print("[yellow]Gravités bloquantes ou majeures sans document source (A VERIFIER)[/yellow] :")
        for line in unsourced:
            console.print(f"  - {line}")
    nulls = null_fields(prof)
    if nulls:
        console.print(
            "[yellow]Valeurs non renseignées (null)[/yellow] : les règles qui en dépendent "
            "refuseront de tourner tant qu'elles ne sont pas complétées."
        )
        for name in nulls:
            console.print(f"  - {name}")


if __name__ == "__main__":
    app()
