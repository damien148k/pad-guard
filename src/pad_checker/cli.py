"""Command-line entry point: ``pad-checker``."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

import typer
from rich.console import Console

from pad_checker import __version__
from pad_checker.rules.profile import ProfileError, load_profile, null_fields

app = typer.Typer(
    help="Contrôle qualité de fichiers Prêt à Diffuser (ProRes 422 HQ / DNxHR HQX).",
    no_args_is_help=True,
    add_completion=False,
)
console = Console()
err_console = Console(stderr=True)

EXIT_USAGE = 1
EXIT_NOT_IMPLEMENTED = 3


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
    _not_implemented("analyze")


@app.command()
def report(
    workdir: Path = typer.Argument(..., help="Dossier produit par « analyze »."),
) -> None:
    """Régénère le rapport à partir des JSON d'un dossier d'analyse."""
    _not_implemented("report")


@app.command("validate-profile")
def validate_profile(
    profile: Path = typer.Argument(..., help="Profil de chaîne (YAML)."),
) -> None:
    """Vérifie un profil de chaîne : schéma, champs inconnus, expressions de gravité."""
    try:
        prof = load_profile(profile)
    except ProfileError as exc:
        err_console.print(f"[red]Profil invalide : {exc.path}[/red]")
        for msg in exc.messages:
            err_console.print(f"  - {msg}")
        raise typer.Exit(EXIT_USAGE) from None

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
