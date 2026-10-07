"""Command-line entry point: ``pad-checker``."""

from __future__ import annotations

import time
from enum import Enum
from fractions import Fraction
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from pad_checker import __version__, jsonio
from pad_checker.decode.video import DecoderOpenError, VideoDecoder
from pad_checker.probe import ProbeError, probe_file
from pad_checker.probe.models import ProbeResult
from pad_checker.rules.profile import Profile, ProfileError, load_profile, null_fields

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

_STATUS = {"ok": "[green]OK[/green]", "fail": "[red]ÉCHEC[/red]", "unknown": "[yellow]?[/yellow]"}


class LlmBackend(str, Enum):
    none = "none"
    ollama = "ollama"


def _not_implemented(what: str) -> None:
    err_console.print(f"[yellow]{what} : non implémenté (voir docs/ROADMAP.md).[/yellow]")
    raise typer.Exit(EXIT_NOT_IMPLEMENTED)


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
    llm: LlmBackend = typer.Option(LlmBackend.none, "--llm", help="Synthèse rédigée par un LLM local."),
    thumbnails: bool = typer.Option(False, "--thumbnails", help="Extraire une vignette par événement."),
    quick: bool = typer.Option(False, "--quick", help="Aperçu rapide (1 image sur 25), sans verdict."),
    benchmark: bool = typer.Option(False, "--benchmark", help="Mesure la vitesse de décodage seule."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Affiche la progression détaillée."),
) -> None:
    """Analyse un fichier et produit mesures, événements, verdict et rapport."""
    prof = _load_profile_or_exit(profile)
    for flag, name in ((thumbnails, "--thumbnails"), (quick, "--quick"), (llm != LlmBackend.none, "--llm")):
        if flag:
            err_console.print(f"[yellow]{name} : non implémenté, option ignorée.[/yellow]")

    try:
        result = probe_file(file, prof, profile)
    except ProbeError as exc:
        err_console.print(f"[red]Fichier refusé : {exc}[/red]")
        raise typer.Exit(EXIT_REFUSED) from None
    jsonio.write(out / "probe.json", result)
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
    _not_implemented("Mesures, structure, règles et rapport (Phase 2 et suivantes)")


@app.command()
def report(
    workdir: Path = typer.Argument(..., help="Dossier produit par « analyze »."),
) -> None:
    """Régénère le rapport à partir des JSON d'un dossier d'analyse."""
    _not_implemented("report")


def _load_profile_or_exit(path: Path) -> Profile:
    try:
        return load_profile(path)
    except ProfileError as exc:
        err_console.print(f"[red]Profil invalide : {exc.path}[/red]")
        for msg in exc.messages:
            err_console.print(f"  - {msg}")
        raise typer.Exit(EXIT_USAGE) from None


def _print_probe(result: ProbeResult) -> None:
    v = result.video
    console.print(f"[bold]{Path(result.source.path).name}[/bold] — profil {result.profile.name} v{result.profile.version}")
    console.print(
        f"  {v.codec_name} {v.profile or ''}, {v.width}x{v.height}, {v.r_frame_rate} i/s, "
        f"{v.nb_frames} images, TC {result.timecode or 'absent'}, {len(result.audio_tracks)} piste(s) audio"
    )
    table = Table(title="Contrôles de format", show_lines=False)
    table.add_column("Contrôle")
    table.add_column("Attendu")
    table.add_column("Mesuré")
    table.add_column("Statut", justify="center")
    for check in result.checks:
        table.add_row(check.label, check.expected, check.actual, _STATUS[check.status])
    console.print(table)


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
