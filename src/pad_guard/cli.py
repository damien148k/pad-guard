"""Command-line entry point: ``pad-guard``."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from enum import Enum
from fractions import Fraction
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeRemainingColumn
from rich.table import Table

from pad_guard import __version__, audio_map as amap, draft, jsonio, llm, measure, pipeline, workdir as wd
from pad_guard.decode.video import DecoderOpenError, VideoDecoder
from pad_guard.draft import compare, review
from pad_guard.draft.write import CAPPED
from pad_guard.labels import SEVERITY_LABELS, SEVERITY_ORDER, status_label
from pad_guard.measure import scan as scan_mod
from pad_guard.measure.models import Measurements
from pad_guard.progress import ProgressFile
from pad_guard.probe import ProbeError, probe_file
from pad_guard.probe.models import ProbeResult
from pad_guard.profiles import ResolvedProfile, is_norm, load_norm, resolve_profile
from pad_guard.profiles.resolve import leaves, read_yaml
from pad_guard.report import ReportError
from pad_guard.report import ai as ai_mod
from pad_guard.rules.engine import RulesError
from pad_guard.rules.models import Verdict
from pad_guard.rules.profile import Profile, ProfileError, ProfileValueError, null_fields
from pad_guard.structure import StructureError
from pad_guard.structure.bars import BarsError

app = typer.Typer(
    help="PAD Guard : contrôle qualité de fichiers Prêt à Diffuser (masters ProRes, DNxHR…).",
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


def _progress_option():
    return typer.Option(None, "--progress-json",
                        help="Écrit aussi la progression en JSON Lines dans ce fichier (pour l'interface locale).")


class StepName(str, Enum):
    structure = "structure"
    rules = "rules"
    report = "report"


def _utf8_streams() -> None:
    """The messages are French (é, →, ≤): a redirected Windows console would encode them in cp1252
    and fail. Standard output and error are switched to UTF-8 instead."""
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "").replace("_", "")
        if encoding != "utf8" and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


_utf8_streams()  # before any output, --help included


def _version(value: bool) -> None:
    if value:
        console.print(f"PAD Guard {__version__}")
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
    llm_backend: LlmBackend = typer.Option(
        LlmBackend.none, "--llm",
        help="Synthèse et qualifications rédigées par le modèle local (ollama) ; none : synthèse par gabarit."),
    llm_model: str | None = typer.Option(
        None, "--llm-model", help=f"Modèle Ollama (défaut : {llm.DEFAULT_MODEL}, sinon {llm.FALLBACK_MODEL})."),
    llm_refresh: bool = typer.Option(
        False, "--llm-refresh", help=f"Rappelle le modèle même si {wd.LLM_SYNTHESIS} correspond aux entrées."),
    thumbnails: bool | None = typer.Option(
        None, "--thumbnails/--no-thumbnails",
        help="Vignette de chaque anomalie image (par défaut : oui ; sautées avec un avertissement si le fichier source est introuvable lors d'une relance).",
    ),
    quick: bool = typer.Option(False, "--quick", help="Aperçu rapide sans verdict (non implémenté)."),
    benchmark: bool = typer.Option(False, "--benchmark", help="Mesure la vitesse de décodage seule."),
    workers: int = typer.Option(
        0, "--workers", min=0, help="Processus de mesure vidéo (0 = automatique). Sans effet sur les résultats.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Affiche la progression détaillée."),
    progress_json: Path | None = _progress_option(),
) -> None:
    """Analyse un fichier et produit mesures, événements, verdict et rapport."""
    pf = ProgressFile(progress_json)
    resolved = _load_profile_or_exit(profile)
    prof = resolved.profile
    mapping = _audio_map_or_exit(audio_map, prof)
    if quick:
        err_console.print("[yellow]--quick : non implémenté, option ignorée.[/yellow]")
    ai = _ai_options(llm_backend, llm_model, llm_refresh)
    problems = pipeline.preflight(prof, mapping.groups)
    if problems:
        err_console.print(f"[red]Profil incomplet pour cette analyse : {profile}[/red]")
        for msg in problems:
            err_console.print(f"  - {msg}")
        raise typer.Exit(EXIT_USAGE)
    command = _command("analyze", str(file), "--profile", str(profile), "--out", str(out),
                       *(("--audio-map", audio_map) if audio_map else ()), *_thumbnail_flag(thumbnails),
                       *((f"--workers", str(workers)) if workers else ()), *_llm_flags(ai))

    pf.emit("probe", "Lecture du fichier et empreinte SHA-256")
    try:
        result = probe_file(file, prof, profile, mapping)
    except ProbeError as exc:
        err_console.print(f"[red]Fichier refusé : {exc}[/red]")
        raise typer.Exit(EXIT_REFUSED) from None
    if not benchmark:
        pipeline.start_run(out, profile, command, resolved)
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

    measurements = _measure(result, prof, out, workers, pf)
    _print_measurements(measurements, out)
    _steps(lambda: pipeline.run_steps(out, prof, "structure", thumbnails, _progress(verbose, pf), ai,
                                      on_step=pf.emit))
    pipeline.finish_run(out)
    _print_ai(ai)
    _finish(out, pf)


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
    thumbnails: bool | None = typer.Option(
        None, "--thumbnails/--no-thumbnails",
        help="Vignette de chaque anomalie image (par défaut : oui ; sautées avec un avertissement si le fichier source est introuvable lors d'une relance).",
    ),
    llm_backend: LlmBackend = typer.Option(
        LlmBackend.none, "--llm",
        help="Synthèse et qualifications rédigées par le modèle local (ollama) ; none : synthèse par gabarit."),
    llm_model: str | None = typer.Option(
        None, "--llm-model", help=f"Modèle Ollama (défaut : {llm.DEFAULT_MODEL}, sinon {llm.FALLBACK_MODEL})."),
    llm_refresh: bool = typer.Option(
        False, "--llm-refresh", help=f"Rappelle le modèle même si {wd.LLM_SYNTHESIS} correspond aux entrées."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Affiche la progression détaillée."),
    progress_json: Path | None = _progress_option(),
) -> None:
    """Relance structure, règles et rapport à partir des JSON existants, sans refaire les mesures."""
    pf = ProgressFile(progress_json)
    if profile is not None:
        prof = _load_profile_or_exit(profile).profile
        problems = pipeline.preflight(prof, prof.audio.groups)
        if problems:
            err_console.print(f"[red]Profil incomplet pour cette analyse : {profile}[/red]")
            for msg in problems:
                err_console.print(f"  - {msg}")
            raise typer.Exit(EXIT_USAGE)
    ai = _ai_options(llm_backend, llm_model, llm_refresh)
    command = _command("rerun", str(workdir), "--from", from_step.value, *(("--profile", str(profile)) if profile else ()),
                       *_thumbnail_flag(thumbnails), *_llm_flags(ai))
    _steps(lambda: pipeline.rerun(workdir, from_step.value, profile, command, thumbnails, _progress(verbose, pf), ai,
                                  on_step=pf.emit))
    _print_ai(ai)
    _finish(workdir, pf)


@app.command()
def report(
    workdir: Path = typer.Argument(..., help="Dossier produit par « analyze »."),
    thumbnails: bool | None = typer.Option(
        None, "--thumbnails/--no-thumbnails",
        help="Vignette de chaque anomalie image (par défaut : oui ; sautées avec un avertissement si le fichier source est introuvable lors d'une relance).",
    ),
    llm_backend: LlmBackend = typer.Option(
        LlmBackend.none, "--llm",
        help="Synthèse et qualifications rédigées par le modèle local (ollama) ; none : synthèse par gabarit."),
    llm_model: str | None = typer.Option(
        None, "--llm-model", help=f"Modèle Ollama (défaut : {llm.DEFAULT_MODEL}, sinon {llm.FALLBACK_MODEL})."),
    llm_refresh: bool = typer.Option(
        False, "--llm-refresh", help=f"Rappelle le modèle même si {wd.LLM_SYNTHESIS} correspond aux entrées."),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Affiche la progression détaillée."),
) -> None:
    """Régénère le rapport à partir des JSON d'un dossier d'analyse (= rerun --from report)."""
    ai = _ai_options(llm_backend, llm_model, llm_refresh)
    command = _command("report", str(workdir), *_thumbnail_flag(thumbnails), *_llm_flags(ai))
    _steps(lambda: pipeline.rerun(workdir, "report", None, command, thumbnails, _progress(verbose), ai))
    _print_ai(ai)
    _finish(workdir)


def _ai_options(backend: LlmBackend, model: str | None, refresh: bool) -> ai_mod.Options | None:
    if backend == LlmBackend.none:
        for flag, given in (("--llm-model", model), ("--llm-refresh", refresh)):
            if given:
                err_console.print(f"[yellow]{flag} : sans effet sans « --llm ollama ».[/yellow]")
        return None
    return ai_mod.Options(model=model, refresh=refresh)


def _llm_flags(ai: ai_mod.Options | None) -> tuple[str, ...]:
    if ai is None:
        return ()
    return ("--llm", "ollama", *(("--llm-model", ai.model) if ai.model else ()),
            *(("--llm-refresh",) if ai.refresh else ()))


def _print_ai(ai: ai_mod.Options | None) -> None:
    """What the local model did, on the console (the report says it too)."""
    if ai is None or ai.outcome is None:
        return
    o = ai.outcome
    if o.model is None:
        err_console.print(f"[yellow]IA : non utilisée ({escape(o.fallback or '')}) : synthèse par gabarit.[/yellow]")
        return
    how = (f"réponses reprises de {wd.LLM_SYNTHESIS}, sans appel au modèle" if o.reused
           else f"{o.calls} requête(s) en {o.elapsed:g} s, contexte {o.num_ctx} jetons")
    console.print(f"IA locale {o.model} : {how}")
    console.print(f"  qualifications : {len(o.qualifications)} retenue(s), "
                  f"{o.requested - len(o.qualifications)} laissée(s) vide(s) sur {o.requested}")
    if o.paragraphs is None:
        err_console.print(f"[yellow]  synthèse IA écartée : {escape(o.fallback or '')}[/yellow]")
    else:
        console.print("  synthèse IA retenue (à relire)")


def _thumbnail_flag(thumbnails: bool | None) -> tuple[str, ...]:
    return () if thumbnails is None else ("--thumbnails",) if thumbnails else ("--no-thumbnails",)


def _command(*args: str) -> str:
    return subprocess.list2cmdline(["pad-guard", *args])


def _progress(verbose: bool, pf: ProgressFile | None = None):
    def show(msg: str) -> None:
        if verbose:
            err_console.print(f"[dim]{msg}[/dim]")
        if pf is not None:
            pf.log(msg)

    return show if verbose or (pf is not None and pf.path is not None) else None


_STEP_ERRORS = (
    wd.WorkdirError, pipeline.PipelineError, StructureError, RulesError, ReportError, ProfileValueError, BarsError,
)


def _steps(action) -> None:
    try:
        action()
    except ProfileError as exc:
        raise _profile_error(exc) from None
    except _STEP_ERRORS as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(EXIT_USAGE) from None
    except DecoderOpenError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(EXIT_REFUSED) from None


def _finish(out: Path, pf: ProgressFile | None = None) -> None:
    verdict = jsonio.read(out / wd.VERDICT, Verdict)
    if pf is not None:
        pf.emit("done", status_label(verdict.status, verdict.indicative), status=verdict.status,
                indicative=verdict.indicative)
    colour = "red" if verdict.status != "CONFORME" else "yellow" if verdict.indicative else "green"
    counts = ", ".join(f"{verdict.counts[s]} {SEVERITY_LABELS[s]}" for s in SEVERITY_ORDER)
    if verdict.indicative:
        console.print("[bold yellow]PROFIL NON VALIDÉ — résultat indicatif[/bold yellow]")
    label = status_label(verdict.status, verdict.indicative)
    console.print(f"[bold {colour}]{label}[/bold {colour}] — score {verdict.score:g}/100 ({counts})")
    for reason in verdict.reasons:
        console.print(f"  - {reason}")
    console.print(f"Rapport : {out / wd.REPORT_MD} et {out / wd.REPORT_PDF}")
    if verdict.status != "CONFORME":
        raise typer.Exit(EXIT_NON_CONFORME)


def _profile_error(exc: ProfileError) -> typer.Exit:
    err_console.print(f"[red]Profil invalide : {exc.path}[/red]")
    for msg in exc.messages:
        err_console.print(f"  - {msg}")
    return typer.Exit(EXIT_USAGE)


def _load_profile_or_exit(path: Path) -> ResolvedProfile:
    """Effective profile (profile + inherited norms), or exit with the reasons."""
    try:
        return resolve_profile(path)
    except ProfileError as exc:
        raise _profile_error(exc) from None


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


def _measure(result: ProbeResult, prof: Profile, out: Path, workers: int, pf: ProgressFile | None = None) -> Measurements:
    total = result.video.nb_frames
    start = time.perf_counter()
    try:
        with Progress(
            TextColumn("Mesures"), BarColumn(), MofNCompleteColumn(), TimeRemainingColumn(),
            console=err_console, transient=True,
        ) as bar:
            task = bar.add_task("images", total=total)
            pf = pf or ProgressFile(None)
            pf.emit("measure_video", "Mesures image : niveaux, gamut, différences entre images", done=0, total=total)

            def on_frames(done: int) -> None:
                bar.update(task, completed=done)
                pf.counter("measure_video", done, total)

            m = measure.run(result, prof, out, workers or None, progress=on_frames,
                            on_audio=lambda: pf.emit("measure_audio", "Mesures audio : loudness, true peak, silences"))
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
    s = m.scan
    console.print(f"Balayage : drapeau {s.field_order or 'absent'}, détecté {scan_mod.SCAN_LABELS[s.detected]} "
                  f"({s.combed_frames} image(s) peignée(s) sur {s.moving_frames} en mouvement)")
    warning = scan_mod.warning(s)
    if warning:
        err_console.print(f"[yellow]Attention : {warning}.[/yellow]")
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
    """Vérifie un profil de chaîne ou une norme : schéma, normes héritées, cycles, sources, gravités."""
    try:
        norm = load_norm(profile) if is_norm(read_yaml(profile)) else None
    except ProfileError as exc:
        raise _profile_error(exc) from None
    if norm is not None:
        d = norm.meta.document
        console.print(f"[green]Norme valide[/green] : {norm.name} — {d.title} ({d.version})")
        count = len(leaves({k: v for k, v in norm.raw.items() if k != "sources"}))
        console.print(f"  {count} valeur(s), chacune avec sa source.")
        return
    resolved = _load_profile_or_exit(profile)
    prof = resolved.profile
    meta = prof.meta
    console.print(f"[green]Profil valide[/green] : {meta.name} v{meta.version} ({meta.broadcaster})")
    console.print(f"  Source : {meta.source_document}")
    console.print(f"  Normes héritées : {', '.join(meta.extends) or 'aucune'}")
    if meta.status == "validated":
        console.print(f"  Statut : validé par {meta.validated_by} le {meta.validated_at.isoformat()}")
    else:
        console.print("  Statut : [yellow]brouillon (draft)[/yellow] — les rapports seront indicatifs")
    console.print(f"  Empreinte du profil effectif : {resolved.fingerprint}")
    if resolved.conflicts:
        console.print(f"  {len(resolved.conflicts)} valeur(s) redéfinie(s) par rapport aux normes : "
                      "voir « pad-guard explain-profile ».")
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


def _value(value: object) -> str:
    if isinstance(value, list) and value and all(isinstance(r, dict) and "source" in r for r in value):
        # Severity chain: "if ... -> major ; else -> minor".
        return " ; ".join(f"{r['if']} → {r['then']}" if "if" in r else f"sinon → {r['else']}" for r in value)
    return json.dumps(value, ensure_ascii=False)


@app.command("explain-profile")
def explain_profile(
    profile: Path = typer.Argument(..., help="Profil de chaîne (YAML)."),
) -> None:
    """Affiche le profil effectif : chaque valeur, le fichier d'où elle vient, sa source, et les conflits."""
    resolved = _load_profile_or_exit(profile)
    meta = resolved.profile.meta
    status = (f"validé par {meta.validated_by} le {meta.validated_at.isoformat()}" if meta.status == "validated"
              else "[yellow]brouillon (draft)[/yellow]")
    console.print(f"[bold]{meta.name}[/bold] v{meta.version} ({meta.broadcaster}) — {status}")
    console.print(f"Empreinte du profil effectif : {resolved.fingerprint}")
    layers = Table(title="Couches appliquées (la dernière gagne)")
    for col in ("Ordre", "Fichier", "Document", "SHA-256"):
        layers.add_column(col)
    for i, layer in enumerate(resolved.layers, start=1):
        layers.add_row(str(i), layer.file, layer.document, layer.sha256[:16] + "…")
    console.print(layers)

    values = dict(leaves({k: v for k, v in resolved.values.items() if k != "meta"}))
    table = Table(title="Profil effectif", show_lines=False)
    for col in ("Champ", "Valeur", "Origine", "Source"):
        table.add_column(col, overflow="fold")
    for path, value in values.items():
        origin = resolved.origins.get(path)
        file = origin.file if origin else "?"
        mark = " [yellow](redéfini)[/yellow]" if origin and origin.replaced else ""
        table.add_row(path, _value(value), file + mark, (origin.source if origin else None) or "[dim]non citée[/dim]")
    console.print(table)

    if resolved.conflicts:
        conflicts = Table(title="Conflits : valeurs redéfinies avec une autre valeur")
        for col in ("Champ", "Valeur retenue", "Fichier", "Valeur remplacée", "Remplacée de"):
            conflicts.add_column(col, overflow="fold")
        for c in resolved.conflicts:
            conflicts.add_row(c.path, _value(c.value), c.file, _value(c.replaced_value), c.replaced_file)
        console.print(conflicts)
    else:
        console.print("Aucun conflit avec les normes héritées.")
    nulls = null_fields(resolved.profile)
    if nulls:
        console.print("[yellow]Valeurs non renseignées (null)[/yellow] : " + ", ".join(nulls))


@app.command("draft-profile")
def draft_profile(
    pdf_file: Path = typer.Argument(..., help="PDF du cahier des charges du diffuseur (dans diffuseurs/)."),
    name: str = typer.Option(..., "--name", "-n", help="Nom du profil, ex. france_tv_hd."),
    model: str | None = typer.Option(
        None, "--model", help=f"Modèle Ollama (défaut : {llm.DEFAULT_MODEL}, sinon {llm.FALLBACK_MODEL})."),
    broadcaster: str | None = typer.Option(None, "--broadcaster", help="Nom du diffuseur (défaut : le nom du profil)."),
    out_dir: Path = typer.Option(draft.DRAFTS, "--out-dir", help="Dossier des brouillons."),
    num_ctx: int | None = typer.Option(
        None, "--num-ctx", min=2048,
        help="Taille du contexte en jetons (défaut : calculée sur la plus grosse demande, plus la réponse)."),
    repeat_penalty: float | None = typer.Option(
        llm.REPEAT_PENALTY, "--repeat-penalty", min=1.0,
        help="Pénalité de répétition d'Ollama (1.0 : aucune ; enregistrée dans le .llm.jsonl)."),
    progress_json: Path | None = _progress_option(),
) -> None:
    """Propose un profil brouillon à partir du PDF d'un diffuseur, avec le modèle local (Ollama)."""
    pf = ProgressFile(progress_json)
    pf.emit("read", "Lecture du PDF")
    client = _ollama_or_exit(model)
    client.num_ctx = num_ctx
    client.repeat_penalty = repeat_penalty
    console.print(f"Modèle local : [bold]{client.model}[/bold] (Ollama, rien ne sort de la machine)")
    start = time.perf_counter()
    with Progress(TextColumn("{task.description}"), BarColumn(), MofNCompleteColumn(), TimeRemainingColumn(),
                  console=err_console, transient=True) as bar:
        task = bar.add_task("Lecture du PDF", total=None)

        def on_read(doc) -> None:
            images = sum(p.needs_image for p in doc.pages)
            console.print(f"{doc.path.name} : {len(doc.pages)} pages, {images} rendue(s) en image, "
                          f"SHA-256 {doc.sha256}")
            bar.update(task, description="Extraction (lots de pages)")
            pf.emit("extract", f"{len(doc.pages)} pages lues, extraction par le modèle local", pages=len(doc.pages))

        def on_progress(done: int, total: int) -> None:
            if done == 0:
                console.print(f"Contexte : {client.num_ctx} jetons" + ("" if num_ctx else " (calculé)"))
            bar.update(task, completed=done, total=total)
            pf.counter("extract", done, total)

        try:
            x, files = draft.make_draft(pdf_file, name, client, out_dir, broadcaster, progress=on_progress,
                                        on_read=on_read)
        except draft.DraftError as exc:
            err_console.print(f"[red]Brouillon impossible : {exc}[/red]")
            raise typer.Exit(EXIT_USAGE) from None
        finally:
            client.release()  # keep_alive 0: the model leaves the GPU memory
    elapsed = time.perf_counter() - start
    counts: dict[str, int] = {}
    for r in x.fields:
        counts[r.status] = counts.get(r.status, 0) + 1
    console.print(f"Extraction : {x.batches} lot(s) en {elapsed:.0f} s")
    for status, n in sorted(counts.items()):
        console.print(f"  {status} : {n} champ(s)")
    console.print(f"  non trouvés : {len(x.not_found)} champ(s)")
    for n in x.capped_pages:
        console.print(f"[bold red]Page {n} : {CAPPED}[/bold red]")
    cited = x.cited_norms()
    console.print("Normes citées par le document : " + (", ".join(cited) if cited else "aucune"))
    console.print(f"meta.extends proposé : {', '.join(draft.proposed_extends(list(cited)))}", highlight=False)
    console.print(f"Brouillon : {files['yaml']}\n  détail : {files['findings']}\n  réponses du modèle : {files['log']}")
    console.print(f"À relire avec : pad-guard review-profile {files['yaml']}")
    pf.emit("done", "Brouillon écrit", draft=str(files["yaml"]))


def _ollama_or_exit(model: str | None) -> llm.OllamaClient:
    probe = llm.OllamaClient()
    try:
        installed = probe.installed()
    except llm.LLMError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(EXIT_USAGE) from None
    wanted = [model] if model else [llm.DEFAULT_MODEL, llm.FALLBACK_MODEL]
    found = next((m for m in wanted if m in installed), None)
    if found is None:
        err_console.print(f"[red]Modèle absent d'Ollama : {wanted[0]}. Lancer « ollama pull {wanted[0]} ».[/red]")
        raise typer.Exit(EXIT_USAGE)
    if found != wanted[0]:
        err_console.print(f"[yellow]{wanted[0]} absent : repli sur {found} "
                          f"(« ollama pull {wanted[0]} » pour le modèle par défaut).[/yellow]")
    return llm.OllamaClient(model=found)


@app.command("review-profile")
def review_profile(
    draft_file: Path = typer.Argument(..., help="Brouillon produit par draft-profile (profiles/drafts/<nom>.yaml)."),
    base: Path | None = typer.Option(
        None, "--base", help="Profil de base pour les valeurs absentes du PDF (défaut : profiles/<nom>.yaml, sinon le gabarit)."),
    out: Path | None = typer.Option(None, "--out", help="Profil validé à écrire (défaut : profiles/<nom>.yaml)."),
    everything: bool = typer.Option(
        False, "--tous", help="Relire aussi les champs dont toutes les propositions ont été rejetées."),
) -> None:
    """Relit un brouillon champ par champ, puis écrit le profil validé (status: validated)."""
    try:
        rv = review.load(draft_file, base)
    except review.ReviewError as exc:
        err_console.print(f"[red]{exc}[/red]")
        raise typer.Exit(EXIT_USAGE) from None
    out = out or (review.ROOT / "profiles" / f"{rv.meta['name']}.yaml")
    console.print(f"Relecture de [bold]{draft_file}[/bold] : {len(rv.fields)} champ(s) extrait(s) ; "
                  f"profil de base {rv.base}")
    skipped = review.ask_fields(rv, ask=lambda text: typer.prompt(text, default="", show_default=False),
                                say=lambda text: console.print(text, markup=False, highlight=False),
                                everything=everything,
                                alert=lambda text: console.print(f"[bold red]{escape(text)}[/bold red]", highlight=False))
    if skipped:
        console.print(f"\n{len(skipped)} champ(s) dont toutes les propositions ont été rejetées n'ont pas été "
                      "relus : ils gardent la valeur du profil de base (A VERIFIER). Les relire avec --tous :")
        console.print(", ".join(f["path"] for f in skipped), markup=False, highlight=False)
    review.ask_references(rv, ask=lambda text: typer.prompt(text, default="", show_default=False),
                          say=lambda text: console.print(text, markup=False, highlight=False),
                          alert=lambda text: console.print(f"[bold red]{escape(text)}[/bold red]", highlight=False))
    answers = review.save_answers(rv)
    console.print(f"Réponses enregistrées dans {answers}")
    data, comments = review.build(rv)
    review.validate(data, "(validation en cours)")
    ask = lambda text: typer.prompt(text, default="", show_default=False)  # noqa: E731
    say = lambda text: console.print(text, markup=False, highlight=False)  # noqa: E731
    asked: set[str] = set()
    while True:
        try:
            resolved, tmp = review.write(rv, out, data, comments)
            break
        except review.ReviewError as exc:
            missing = [p for p in review.missing_fields(exc) if p not in asked]
            if not missing:  # not something the reviewer can fill in here
                err_console.print(f"[red]{exc}[/red]")
                raise typer.Exit(EXIT_USAGE) from None
            asked.update(missing)
            review.complete(data, comments, missing, rv.meta.get("source_document", "document"), ask, say,
                            rv.glossary)
    tmp.unlink(missing_ok=True)
    risks = review.norm_only_rules(resolved)
    if risks:
        console.print("[bold red]ATTENTION : règles bloquantes ou majeures dont la valeur ne viendrait que d'une "
                      "norme. Elles seront plafonnées à mineur : une erreur réelle ne rendra pas le PAD "
                      "NON-CONFORME.[/bold red]")
        for line in risks:
            console.print(f"[red]  - {line}[/red]")
        if not _yes("Valider quand même ? [o/N]"):
            console.print("Rien n'a été écrit. Compléter ces valeurs (relancer la relecture) puis valider.")
            raise typer.Exit(EXIT_USAGE)
    unsourced = sorted(p for p, c in comments.items() if c.startswith("A VERIFIER"))
    if unsourced:
        console.print(f"[yellow]{len(unsourced)} valeur(s) reprise(s) du profil de base sans citation du document "
                      "(A VERIFIER dans le fichier).[/yellow]")
    who = ""
    while not who:
        who = typer.prompt("Nom du validateur").strip()
    if out.exists() and not _yes(f"{out} existe : le remplacer ? [o/N]"):
        raise typer.Exit(EXIT_USAGE)
    review.validate(data, who)
    resolved, tmp = review.write(rv, out, data, comments)
    review.finish(tmp, out)
    console.print(f"[green]Profil validé[/green] : {out} (validé par {who}), empreinte {resolved.fingerprint}")


def _yes(question: str) -> bool:
    """French yes/no question: o, oui, y, yes; anything else (or nothing) is no."""
    return typer.prompt(question, default="", show_default=False).strip().lower() in ("o", "oui", "y", "yes")


@app.command("compare-profiles")
def compare_profiles(
    a: Path = typer.Argument(..., help="Premier profil (ou brouillon)."),
    b: Path = typer.Argument(..., help="Second profil (ou brouillon)."),
    all_rows: bool = typer.Option(False, "--all", help="Afficher aussi les valeurs identiques."),
) -> None:
    """Compare deux profils effectifs (profil + normes héritées) valeur par valeur."""
    try:
        rows = compare.compare(a, b)
    except ProfileError as exc:
        raise _profile_error(exc) from None
    table = Table(title=f"A = {a.name}, B = {b.name}")
    for col in ("Champ", "Écart", "A", "Origine A", "B", "Origine B"):
        table.add_column(col, overflow="fold")
    for r in rows:
        if r.kind == compare.SAME and not all_rows:
            continue
        status = f" [{r.a_status}]" if r.a_status else ""
        table.add_row(r.path, r.kind, ("—" if r.kind == compare.ONLY_B else _value(r.a)) + status, r.a_file or "",
                      "—" if r.kind == compare.ONLY_A else _value(r.b) + (f" [{r.b_status}]" if r.b_status else ""),
                      r.b_file or "")
    console.print(table)
    counts = {k: sum(r.kind == k for r in rows) for k in (compare.SAME, compare.DIFFERENT, compare.ONLY_A, compare.ONLY_B)}
    console.print(", ".join(f"{n} {k}" for k, n in counts.items()))


if __name__ == "__main__":
    app()


@app.command()
def ui(
    port: int = typer.Option(8765, "--port", min=0, max=65535, help="Port local (0 : un port libre)."),
    no_browser: bool = typer.Option(False, "--no-browser", help="N'ouvre pas le navigateur."),
) -> None:
    """Ouvre l'interface locale dans le navigateur (127.0.0.1 seulement, rien ne sort de la machine)."""
    from pad_guard.ui import server

    server.serve(port, open_browser=not no_browser, say=lambda text: console.print(text, highlight=False))
