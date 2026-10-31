"""Step 5: rapport.md and rapport.pdf from the JSON of the analysis directory (SPEC §8).

Reads probe.json, measurements.json (and the JSON Lines files for the annex charts),
structure.json, events.json, verdict.json and run.json. The source file is needed only for
``--thumbnails``. Without the LLM layer the synthesis is generated from the counters; with it
(:mod:`pad_guard.report.ai`), the local model writes the synthesis and suggests a qualification
per anomaly, every word of it checked, and the template comes back at the slightest doubt.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from pad_guard import formats, timecode, workdir as wd
from pad_guard.audio_map import describe, tracks_text
from pad_guard.labels import SEVERITY_LABELS, SEVERITY_ORDER, VIDEO_TYPES, number, status_label, type_label
from pad_guard.decode.video import picture_of
from pad_guard.measure import scan as scan_mod
from pad_guard.measure.models import Measurements
from pad_guard.measure.series import load_audio, load_video
from pad_guard.probe.models import ProbeResult
from pad_guard.profiles import fingerprint, from_json
from pad_guard.profiles.resolve import HOUSE
from pad_guard.report import ai as ai_mod, charts, pdf, thumbnails as thumbs
from pad_guard.rules import delivery
from pad_guard.rules import scan as scan_rule
from pad_guard.rules.engine import error_key
from pad_guard.rules.models import Event, Events, Verdict
from pad_guard.rules.profile import Profile
from pad_guard.structure.models import Structure

Progress = Callable[[str], None]

KERNELS = {3: "[1 2 1]/4", 5: "[1 4 6 4 1]/16"}
MASK_LEGENDS = {"y_above": "en rouge, Y au-dessus de la tolérance", "y_below": "en bleu, Y en dessous de la tolérance",
                "rgb_out": "en magenta, R, V ou B hors limites"}
_STATUS = {"ok": "OK", "fail": "ÉCHEC", "unknown": "non renseigné", "not_requested": "non demandé"}


class ReportError(Exception):
    """The report cannot be written. The message is user-facing (French)."""


def _cell(value: object) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _db(value: float | None, unit: str) -> str:
    return "silence" if value is None else f"{number(value, 1)} {unit}"


class _Builder:
    def __init__(self, workdir: Path, profile: Profile):
        self.dir = workdir
        self.p = profile
        self.probe = wd.load(workdir, wd.PROBE, ProbeResult, "analyze")
        self.m = wd.load(workdir, wd.MEASUREMENTS, Measurements, "analyze")
        self.st = wd.load(workdir, wd.STRUCTURE, Structure, "structure")
        self.events = wd.load(workdir, wd.EVENTS, Events, "rules").events
        self.verdict = wd.load(workdir, wd.VERDICT, Verdict, "rules")
        if not (self.m.source.sha256 == self.st.source_sha256 == self.verdict.source_sha256):
            raise ReportError("les JSON du dossier ne viennent pas du même fichier source : relancer les étapes")
        self.fps = Fraction(self.m.source.fps)
        self.clock = timecode.Clock(self.fps, self.st.timecode_start, self.st.timecode_format)

    def seconds(self, frames: int) -> str:
        return f"{number(frames / self.fps, 2)} s"

    # --- sections -------------------------------------------------------------------------

    def header(self) -> dict:
        run_file = self.dir / wd.RUN
        run = wd.RunInfo.model_validate_json(run_file.read_text(encoding="utf-8")) if run_file.is_file() else None
        v = self.probe.video
        frames = self.st.frames
        size = self.probe.source.size_bytes
        prof = self.probe.profile
        meta = self.p.meta
        inherits = f", hérite de {', '.join(meta.extends)}" if meta.extends else ""
        if meta.status == "validated":
            status = f"validé par {meta.validated_by} le {meta.validated_at.isoformat()}"
        else:
            status = "brouillon (draft), non validé : résultat indicatif"
        return {
            "indicative": self.verdict.indicative,
            "profile_status": status,
            "fingerprint": fingerprint(self.p),
            "file_name": Path(self.probe.source.path).name,
            "path": self.probe.source.path,
            "sha256": self.probe.source.sha256,
            "size": f"{number(size / 1e9, 2)} Go ({size} octets)",
            "duration": f"{self.clock.duration(frames)} ({frames} images à {self.m.source.fps} i/s)",
            "timecode": (f"{self.clock.tc(0)} → {self.clock.tc(frames - 1)}" if self.st.timecode_start
                         else "absent ou inutilisable (temps compté depuis 00:00:00:00)"),
            "timecode_format": timecode.describe(self.clock.format) if self.st.timecode_start else None,
            "video": f"{v.codec_name} {v.profile or ''}, {v.width}x{v.height}, {v.pix_fmt}, balayage {v.field_order or 'inconnu'}",
            "profile": f"{prof.name} v{prof.version} ({meta.broadcaster}){inherits}",
            "source_document": self.p.meta.source_document,
            "tool_version": self.verdict.tool_version,
            "analyzed_at": run.analyzed_at if run else "inconnue",
            "command": run.command if run else "inconnue",
            "reruns": run.reruns[-3:] if run else [],
        }

    def synthesis(self) -> str:
        v = self.verdict
        name = Path(self.probe.source.path).name
        prof = self.probe.profile
        n = v.counts
        if v.technical:
            parts = [f"Rapport technique du fichier « {name} » (profil {prof.name} v{prof.version}, sans diffuseur) : "
                     "les anomalies sont listées selon les règles Lumiris, sans verdict de conformité."]
        elif v.indicative:
            outcome = "est NON-CONFORME" if v.status == "NON-CONFORME" else "ne présente aucune anomalie bloquante"
            parts = [f"Résultat indicatif, le profil {prof.name} v{prof.version} ({self.p.meta.broadcaster}) n'étant "
                     f"pas validé : le fichier « {name} » {outcome}, avec un score de {number(v.score, 0)}/100."]
        else:
            parts = [f"Le fichier « {name} » est {v.status} au profil {prof.name} v{prof.version} "
                     f"({self.p.meta.broadcaster}), avec un score de {number(v.score, 0)}/100."]
        total = sum(n.values())
        if total == 0:
            parts.append("Aucune anomalie n'a été relevée.")
        else:
            counted = [f"{n[s]} {SEVERITY_LABELS[s]}{'s' if n[s] > 1 and s != 'info' else ''}"
                       for s in SEVERITY_ORDER if n[s]]
            parts.append(f"L'analyse relève {total} anomalie(s) : {', '.join(counted)}.")
            for sev, what in (("blocking", "bloquantes"), ("major", "majeures")):
                kinds = sorted({type_label(e.type) for e in self.events if e.severity == sev})
                if kinds:
                    parts.append(f"Les anomalies {what} concernent : {', '.join(k.lower() for k in kinds)}.")
            if n["minor"] and v.status == "CONFORME" and not v.indicative:
                parts.append("Les anomalies mineures sont tolérées par le profil mais doivent être vérifiées.")
        parts.append("Ce rapport est un pré-contrôle interne : il ne remplace pas le contrôle du diffuseur.")
        return " ".join(parts)

    def checks(self) -> list[dict]:
        scan = scan_rule.evaluate(self.probe, self.m, self.p)
        rows = []
        for c in self.probe.checks:
            if c.id == scan_rule.CHECK_ID:  # scan: what the pictures show, and the flag
                status = ("ok" if scan.event_type is None else "fail") if scan.decided else c.status
                rows.append(dict(label=c.label, expected=c.expected, actual=scan.actual, status=_STATUS[status]))
            else:
                rows.append(dict(label=c.label, expected=c.expected, actual=c.actual, status=_STATUS[c.status]))
        integ = self.m.integrity
        rows.append(dict(
            label="Intégrité du décodage", expected=f"{integ.frames_expected or '?'} images, aucune erreur",
            actual=(f"{integ.frames_decoded} images décodées, {len({error_key(e.message) for e in integ.errors})} "
                    f"erreur(s) distincte(s), {len(integ.pts_discontinuities)} discontinuité(s)"),
            status=_STATUS["ok" if integ.ok else "fail"],
        ))
        rows += [dict(label=c.label, expected=c.expected, actual=c.actual, status=_STATUS[c.status])
                 for c in self.st.checks]
        return rows

    def delivery(self) -> dict:
        """Section « Livraison »: master scan and rate against format.delivery of the profile."""
        c = delivery.compare(self.probe, self.m, self.p)
        s = self.m.scan
        v = self.probe.video
        pct = "—" if s.combed_pct is None else f"{number(s.combed_pct, 1)} %"
        scan = (f"{c.master} ({c.scan_from}) ; drapeau du fichier : {v.field_order or 'absent'} ; détection : "
                f"{scan_mod.SCAN_LABELS[s.detected]}, {s.combed_frames} image(s) peignée(s) sur {s.moving_frames} "
                f"en mouvement ({pct})")
        event = next((e for e in self.events if e.type == "delivery_conversion_required"), None)
        if c.delivery is None:
            conclusion = "Le profil ne décrit pas le format de livraison (format.delivery) : pas de comparaison."
        elif c.differences:
            conclusion = (f"Conversion requise avant livraison : {', '.join(c.differences)} (anomalie "
                          f"{event.id if event else '?'}, information). Ce n'est pas une non-conformité du master.")
        else:
            conclusion = "Balayage et cadence du master conformes au format de livraison : pas de conversion de format."
        if c.codec:
            conclusion += f" Codec de livraison : {c.codec} (le master est transcodé par le prestataire)."
        warning = scan_mod.warning(s)
        return {"master": scan, "expected": c.delivery or "non renseigné dans le profil", "conclusion": conclusion,
                "warning": f"Attention : {warning}." if warning else ""}

    def integrity_errors(self) -> list[dict]:
        by_key: dict[str, set[int]] = {}
        for err in self.m.integrity.errors:
            by_key.setdefault(error_key(err.message), set()).add(err.after_frame)
        rows = []
        for key, frames in sorted(by_key.items(), key=lambda kv: min(kv[1])):
            ordered = sorted(frames)
            shown = ", ".join(f"{f} ({self.clock.tc(f)})" for f in ordered[:8])
            rows.append(dict(key=key, count=len(ordered), frames=shown + (" …" if len(ordered) > 8 else "")))
        return rows

    def audio(self) -> dict:
        a = self.m.audio
        if a is None:
            return {"program": "Le fichier n'a pas de piste audio.", "groups": [], "tracks": [], "rules": ""}
        p = a.program
        where = f"{p.tc_start} → {p.tc_end}" if p.tc_start else f"images {p.frame_start} à {p.frame_end}"
        method = {"file": "fichier entier", "timecode": "début du programme repéré par le timecode",
                  "profile": "début du programme supposé d'après le profil (timecode inutilisable)"}[p.start_method]
        source = "ligne de commande" if self.probe.audio_map.source == "command_line" else "profil"
        program = (f"Mesures globales sur le programme : {where} ({method}"
                   f"{', noir de queue exclu' if p.end_method == 'black_tail' else ''}). "
                   f"Groupes ({source}) : {describe(self.probe.audio_map.groups)}.")
        by_group: dict[str, dict[str, int]] = {}
        for e in self.events:
            if e.type in ("audio_silence", "audio_phase") and e.group:
                key = e.group.split(" (")[0]
                by_group.setdefault(key, {}).setdefault(e.type, 0)
                by_group[key][e.type] += 1
        groups = []
        for name, g in a.groups.items():
            counts = by_group.get(name, {})
            groups.append(dict(
                name=name, tracks=tracks_text(g.group.tracks), integrated=_db(g.integrated_lufs, "LUFS"),
                true_peak=_db(g.true_peak_dbtp, "dBTP"), lra="—" if g.lra_lu is None else _db(g.lra_lu, "LU"),
                short_term=_db(g.short_term_max_lufs, "LUFS"),
                correlation="—" if g.correlation is None else number(g.correlation, 2),
                silences=str(counts.get("audio_silence", 0)), phase=str(counts.get("audio_phase", 0)),
            ))
        group_of = {t: g.name for g in self.probe.audio_map.groups for t in g.tracks}
        tracks = [dict(track=t.track, group=group_of.get(t.track, "hors mapping"), peak=_db(t.peak_dbfs, "dBFS"),
                       true_peak=_db(t.true_peak_dbtp, "dBTP"), rms=_db(t.rms_dbfs, "dBFS"),
                       full_scale=str(t.full_scale_samples)) for t in a.tracks]
        loud = self.p.audio.loudness
        seconds = (p.sample_end - p.sample_start) / a.settings.sample_rate
        short = loud.short is not None and seconds <= loud.long_program_min_seconds
        rs = loud.short if short else loud.long
        rules = (f"programme {'court' if short else 'long'} ({number(seconds / 60, 1)} min) : "
                 f"{number(rs.integrated_lufs)} LUFS ± {number(rs.integrated_tolerance_lu)} LU, true peak ≤ "
                 f"{number(self.p.audio.true_peak_max_dbtp)} dBTP"
                 + (f", LRA ≤ {number(rs.lra_max_lu)} LU" if rs.lra_max_lu is not None else "") + ".")
        return {"program": program, "groups": groups, "tracks": tracks, "rules": rules}

    def ai_inputs(self) -> tuple[dict, list[dict]]:
        """What the model is given (SPEC §8.1): verdict, profile, key probe facts and the events as
        the report shows them; never the frame-by-frame measurements."""
        v, prof, video, s = self.verdict, self.probe.profile, self.probe.video, self.m.scan
        families: dict[tuple, list[int]] = {}
        for e in sorted(self.events, key=lambda e: (SEVERITY_ORDER.index(e.severity), e.id)):
            families.setdefault((type_label(e.type), e.type, e.group, SEVERITY_LABELS[e.severity]), []).append(e.id)
        context = {
            "fichier": Path(self.probe.source.path).name,
            "profil": {"nom": prof.name, "version": prof.version, "diffuseur": self.p.meta.broadcaster,
                       "statut": "validé" if self.p.meta.status == "validated" else "brouillon, non validé"},
            "verdict": {"statut": v.status, "affiche": status_label(v.status, v.indicative, v.technical),
                        "indicatif": v.indicative, "technique": v.technical,
                        "score": number(v.score, 0 if v.score.is_integer() else 1),
                        "anomalies_par_gravite": {SEVERITY_LABELS[k]: v.counts[k] for k in SEVERITY_ORDER},
                        "motifs": v.reasons},
            "probe": {"codec": f"{video.codec_name} {video.profile or ''}".strip(),
                      "image": f"{video.width}x{video.height}", "cadence": self.m.source.fps,
                      "drapeau_de_balayage": video.field_order or "absent",
                      "balayage_detecte": scan_mod.SCAN_LABELS[s.detected],
                      "duree": self.clock.duration(self.st.frames)},
            "anomalies_par_type": [{"type": t, "libelle": label, "groupe": g, "gravite": sev, "nombre": len(ids),
                                    "anomalies": ids} for (label, t, g, sev), ids in families.items()],  # by severity
        }
        events = []
        for e in self.events:
            ranged = e.scope == "range"
            item = {"n": e.id, "type": e.type, "libelle": type_label(e.type), "gravite": SEVERITY_LABELS[e.severity],
                    "groupe": e.group, "portee": "plage" if ranged else "fichier entier",
                    "tc_debut": e.tc_start if ranged else None, "tc_fin": e.tc_end if ranged else None,
                    "duree": self.seconds(e.duration_frames) if ranged else None, "titre": e.title,
                    "valeur": e.value_text, "seuil": e.threshold_text,
                    "surface": None if e.area_pct_max is None else f"{number(e.area_pct_max, 2)} %",
                    "regle": e.severity_source, "source": e.source, "detail": e.detail or None}
            events.append({k: x for k, x in item.items() if x is not None})
        return context, events

    def event_rows(self, thumbnails: dict[int, str], outcome: ai_mod.Outcome | None = None) -> list[dict]:
        rows = []
        for e in self.events:
            ranged = e.scope == "range"
            label = type_label(e.type) + (f" ({e.group})" if e.group else "")
            q = outcome.qualifications.get(e.id) if outcome else None
            rejected = outcome.rejected.get(e.id) if outcome else None
            rows.append(dict(
                id=e.id, tc_start=e.tc_start if ranged else "—", tc_end=e.tc_end if ranged else "—",
                duration=self.seconds(e.duration_frames) if ranged else "global", type=label,
                value=e.value_text, threshold=e.threshold_text,
                area="" if e.area_pct_max is None else f"{number(e.area_pct_max, 2)} %",
                severity=SEVERITY_LABELS[e.severity],
                thumbnail=f"voir {e.id}" if e.id in thumbnails else "",
                title=e.title, group=e.group, detail=e.detail, severity_source=e.severity_source,
                level=e.severity,
                frames=f"{e.frame_start} à {e.frame_end}" if ranged else "fichier entier",
                qualification=f"*{q.value}*" if q else "",
                qualification_detail=(f"qualification suggérée par l'IA, à valider : *{q.value}* ({q.justification})"
                                      if q else f"qualification IA laissée vide : {rejected}" if rejected else ""),
            ))
        return rows

    def event_tables(self, thumbnails: dict[int, str], outcome: ai_mod.Outcome | None = None) -> list[dict]:
        rows = self.event_rows(thumbnails, outcome)
        return [
            dict(title="Bloquantes et majeures",
                 intro="Anomalies qui décident du verdict : à corriger avant livraison.",
                 events=[r for r in rows if r["level"] in ("blocking", "major")]),
            dict(title="À vérifier (mineures et informations)",
                 intro="Tolérées par le profil : à contrôler à l'image ou à l'écoute. Beaucoup viennent de règles "
                       "« DEDUIT » (aucun texte du diffuseur ne les chiffre), plafonnées à mineur.",
                 events=[r for r in rows if r["level"] in ("minor", "info")]),
        ]

    def thumbnail_rows(self, names: dict[int, str]) -> list[dict]:
        rows = []
        for e in self.events:
            if e.id not in names:
                continue
            frame = e.worst_frame if e.worst_frame is not None else e.frame_start
            masks = thumbs.MASKS_BY_TYPE.get(e.type, ())
            legend = ("À gauche l'image, à droite les pixels comptés par la mesure, sur l'image assombrie : "
                      + ", ".join(MASK_LEGENDS[m] for m in masks) + ".") if masks else ""
            rows.append(dict(id=e.id, path=f"{wd.THUMBNAILS}/{names[e.id]}", legend=legend,
                             caption=f"{type_label(e.type)}, image {frame} ({self.clock.tc(frame)})"))
        return rows

    def charts(self) -> dict:
        out_dir = self.dir / wd.CHARTS
        out_dir.mkdir(exist_ok=True)
        video = load_video(self.dir, self.m)
        s = self.m.video_settings
        charts.luma_chart(out_dir / "luminance.png", video["y_p01"], video["y_p99"], float(self.fps),
                          tuple(s.y_legal), tuple(s.y_tolerance))
        result = {"luma": f"{wd.CHARTS}/luminance.png", "loudness": None}
        blocks = load_audio(self.dir, self.m)
        if blocks:
            seconds = self.m.audio.settings.block_samples / self.m.audio.settings.sample_rate
            charts.loudness_chart(out_dir / "loudness.png", {k: b.m for k, b in blocks.items()}, seconds,
                                  self.p.audio.loudness.long.integrated_lufs)
            result["loudness"] = f"{wd.CHARTS}/loudness.png"
        return result

    def matrix_reason(self) -> str:
        """Why the measurements used this matrix (formats.file_matrix); the matrix of older measures may differ."""
        v = self.probe.video
        matrix, why = formats.file_matrix(v.color_space, v.height)
        return why if matrix == self.m.video_settings.matrix else "matrice du profil, mesures antérieures"

    def parameters(self) -> list[str]:
        p, s = self.p, self.m.video_settings
        v = p.video
        st = p.structure
        prefilter = (f"horizontal {s.prefilter_taps} points, noyau {KERNELS[s.prefilter_taps]} (A VERIFIER : "
                     "EBU R 103 v3.0 recommande 7 coefficients horizontaux et 3 verticaux, non pris en charge)"
                     if s.prefilter_taps else "aucun")
        # In frames at the rate of this file (the profile may give them in seconds).
        minimums = {t: p.rules.min_frames(t, self.fps) for t in {*p.rules.min_event_frames, *p.rules.min_event_seconds}}
        out = [
            f"Vidéo : Y légal {s.y_legal[0]}–{s.y_legal[1]} ; Y toléré {number(v.y_tolerance_low_pct)} % / "
            f"{number(v.y_tolerance_high_pct)} % soit {s.y_tolerance[0]}–{s.y_tolerance[1]} ; RVB "
            f"{number(v.rgb_min_pct)} % / {number(v.rgb_max_pct)} % soit {s.rgb[0]}–{s.rgb[1]} (codes 10 bits, "
            f"bornes incluses) ; anomalie si la surface hors tolérance "
            f"{'dépasse' if v.out_of_range_area_error == 'above' else 'atteint'} {number(v.max_out_of_range_area_pct)} % "
            "de l'image.",
            f"Préfiltre avant mesure des niveaux : {prefilter}.",
            f"Conversion RVB : matrice {s.matrix} ({self.matrix_reason()}), chroma 4:2:2 interpolée linéairement, "
            "sans écrêtage.",
            f"Structure : amorces « {st.leaders} », TC de départ {st.timecode.file_start}, programme à "
            f"{st.timecode.program_start} (± {st.timecode.tolerance_frames} image(s)) ; noir si y_p99 < {st.black.y_max}"
            f" et son < {number(st.black.silence_dbfs)} dBFS.",
            f"Images figées : différence moyenne < {number(st.freeze.threshold, 2)} pendant au moins "
            f"{number(st.freeze.min_seconds)} s ; PSE : {'activé' if st.pse.enabled else 'désactivé'}, plus de "
            f"{st.pse.max_flashes_per_second} flashs/s (variation > {number(st.pse.flash_min_delta_pct, 0)} % de "
            f"luminance sur plus de {number(st.pse.flash_min_area_pct, 0)} % de l'image).",
            f"Audio : true peak ≤ {number(p.audio.true_peak_max_dbtp)} dBTP ; silence < {number(p.audio.silence_dbfs)} "
            f"dBFS pendant plus de {number(p.audio.silence_max_seconds) if p.audio.silence_max_seconds else '?'} s ; "
            f"phase : corrélation < {number(p.audio.phase_min_correlation, 2)} pendant plus de "
            f"{number(p.audio.phase_min_seconds) if p.audio.phase_min_seconds else '?'} s.",
            f"Événements : images fusionnées si moins de {p.rules.gap_frames(self.fps)} image(s) les séparent ; durées "
            f"minimales {', '.join(f'{k} {n}' for k, n in sorted(minimums.items()))} ; "
            f"{p.rules.max_major} anomalie(s) majeure(s) tolérée(s) ; score = {p.rules.score_formula}.",
        ]
        return out

    def norm_gaps(self) -> list[str]:
        """Client values that differ from a norm: information, no effect on the verdict (CLAUDE.md principle 2)."""
        path = self.dir / wd.EFFECTIVE_PROFILE
        if not path.is_file():
            return []
        resolved = from_json(json.loads(path.read_text(encoding="utf-8")), path)
        norms = {layer.file: layer.document.split(" — ")[0] for layer in resolved.layers
                 if layer.kind == "norm" and layer.name != HOUSE}
        client = self.p.meta.broadcaster

        def show(value: object) -> str:
            return number(value, 1) if isinstance(value, float) else str(value)

        return [f"{c.path} : {client} {show(c.value)} ; {norms[c.replaced_file]} {show(c.replaced_value)}"
                for c in resolved.conflicts if c.file == resolved.profile_file and c.replaced_file in norms]

    def notes(self, outcome: ai_mod.Outcome | None = None) -> list[str]:
        notes = list(self.st.limitations)
        notes.append("PSE : approximation inspirée d'ITU-R BT.1702 (variations de luminance relative sur l'image "
                     "entière) ; ce n'est pas un test Harding certifié.")
        if self.st.letterbox is not None:
            notes.append(f"Format d'image : cadre du programme pris sur une image toutes les "
                         f"{number(self.st.letterbox.sample_seconds, 0)} s, ses quatre bords comparés au format du "
                         "profil centré ; puis chaque image du programme comparée à ce cadre (« Changement de "
                         "cadre »), sur les seuls bords mesurables (un bord sombre, un fondu, un carton noir ne "
                         "comptent pas).")
        if self.p.audio.loudness.long.short_term_dialogue_excursion_lu is not None:
            notes.append("Short term : seule l'excursion au-dessus de la cible est contrôlée, sur tout le programme ; "
                         "le dialogue n'est pas détecté automatiquement.")
        if outcome is None:
            notes.append("Qualification suggérée : vide, la couche IA est désactivée.")
        else:
            notes.append(ai_note(outcome))
        notes.append("Les seuils sont ceux du profil ; une valeur marquée « A VERIFIER » ou « DEDUIT » dans le profil "
                     "est une interprétation à confirmer.")
        notes += self.version_notes()
        return notes

    def version_notes(self) -> list[str]:
        """A norm cited in another version than the one of normes/ (« CST-RT-040 cite EBU R 103 v2.0, version
        appliquée : version 3.0 ») : information, from the effective profile."""
        path = self.dir / wd.EFFECTIVE_PROFILE
        if not path.is_file():
            return []
        return [f"Version de norme : {n}." for n in from_json(json.loads(path.read_text(encoding="utf-8")), path).notes]

    def view(self, sections: dict, names: dict[int, str], outcome: ai_mod.Outcome | None) -> dict:
        """rapport.json: what rapport.md shows, as data, for the local interface (Phase 5). The
        interface displays it as is and computes nothing. Anomalies are named by ``Event.key``."""
        v = self.verdict
        keys = [e.key for e in self.events]
        duplicates = sorted({k for k in keys if keys.count(k) > 1})
        frames = self.st.frames
        events = []
        for e, row in zip(self.events, self.event_rows(names, outcome)):
            q = outcome.qualifications.get(e.id) if outcome else None
            events.append(dict(
                key=e.key, id=e.id, type=e.type, label=row["type"], title=e.title, severity=e.severity,
                severity_label=row["severity"], severity_source=e.severity_source, scope=e.scope,
                frame_start=e.frame_start, frame_end=e.frame_end, tc_start=row["tc_start"], tc_end=row["tc_end"],
                duration=row["duration"], value=e.value_text, threshold=e.threshold_text, area=row["area"],
                group=e.group, detail=e.detail,
                thumbnail=f"{wd.THUMBNAILS}/{names[e.id]}" if e.id in names else None,
                qualification=q.value if q else None, qualification_justification=q.justification if q else None,
                qualification_empty_reason=outcome.rejected.get(e.id) if outcome else None,
            ))
        ticks = 6
        layers = []
        path = self.dir / wd.EFFECTIVE_PROFILE
        if path.is_file():
            resolved = from_json(json.loads(path.read_text(encoding="utf-8")), path)
            layers = [layer.document.split(" — ")[0] for layer in resolved.layers if layer.kind == "norm"]
        h = dict(sections["h"], reruns=[r.model_dump(mode="json") for r in sections["h"]["reruns"]])
        return {
            "schema_version": 1,
            "tool_version": v.tool_version,
            "header": h,
            "profile": {"name": self.p.meta.name, "version": self.p.meta.version, "status": self.p.meta.status,
                        "broadcaster": self.p.meta.broadcaster, "norms": layers},
            "verdict": {"status": v.status, "indicative": v.indicative, "technical": v.technical,
                        "label": sections["status"],
                        "score": v.score, "score_text": sections["score"], "score_formula": v.score_formula,
                        "counts": v.counts, "counts_labels": {s: SEVERITY_LABELS[s] for s in SEVERITY_ORDER},
                        "max_major": v.max_major, "reasons": v.reasons},
            "synthesis": {"text": sections["synthesis"], "note": sections["synthesis_note"],
                          "by_ai": bool(outcome and outcome.paragraphs is not None),
                          "warnings": sections["ai_warnings"]},
            "delivery": sections["delivery"],
            "checks": sections["checks"],
            "integrity_errors": sections["integrity_errors"],
            "audio": sections["audio"],
            "timeline": {"frames": frames, "tc_start": self.clock.tc(0), "tc_end": self.clock.tc(frames - 1),
                         "ticks": [{"pct": round(100 * i / ticks, 3),
                                    "label": self.clock.tc(min(frames - 1, round((frames - 1) * i / ticks)))[:8]}
                                   for i in range(ticks + 1)]},
            "events": events,
            "duplicate_keys": duplicates,
            "thumbnails_note": sections["thumbnails_note"],
            "charts": sections["charts"],
            "parameters": sections["parameters"],
            "norm_gaps": sections["norm_gaps"],
            "notes": sections["notes"],
        }


def ai_note(outcome: ai_mod.Outcome) -> str:
    """« Méthodes et limites » line of the AI layer (French)."""
    if outcome.model is None:
        return (f"Synthèse et qualification suggérée : couche IA demandée mais non utilisée ({outcome.fallback}) ; "
                "synthèse par gabarit, colonne de qualification vide.")
    kept = len(outcome.qualifications)
    return (f"Synthèse et qualification suggérée : rédigées par le modèle local {outcome.model} (Ollama, rien ne "
            f"sort de la machine), prompt {ai_mod.PROMPT_VERSION}. Le modèle reçoit le verdict, le profil, les "
            "caractéristiques du fichier, la liste des anomalies et leurs vignettes, jamais les mesures image par "
            "image. Chaque nombre, timecode, numéro et type d'anomalie qu'il écrit doit figurer dans ces données, et "
            "le verdict écrit doit être celui des règles : sinon la synthèse par gabarit est utilisée. Une "
            "qualification hors liste, non justifiée, contradictoire, ou dont la justification affirme qu'une "
            "anomalie respecte son seuil, reste vide. Qualifications : "
            f"{kept} retenue(s), {outcome.requested - kept} laissée(s) vide(s) sur {outcome.requested} anomalie(s) "
            "bloquante(s), majeure(s) ou mineure(s). Ce sont des suggestions à valider à l'image ou à l'écoute : "
            "le verdict, le score et les gravités ne dépendent pas de l'IA.")


def synthesis_section(template: str, outcome: ai_mod.Outcome | None) -> tuple[str, str, list[str]]:
    """(text, note under it, warnings) of section 3."""
    if outcome is None:
        return template, "*Synthèse générée par gabarit à partir des compteurs (couche IA désactivée).*", []
    warnings = []
    if outcome.paragraphs is not None:
        text = "\n\n".join(_paragraph(p) for p in outcome.paragraphs)
        note = (f"*Rédigée par IA locale ({outcome.model}, prompt {ai_mod.PROMPT_VERSION}) à partir des anomalies "
                "ci-dessous ; à relire. Le verdict est calculé par des règles.*")
    else:
        text = template
        note = ("*Synthèse générée par gabarit à partir des compteurs : la synthèse rédigée par l'IA locale a été "
                "écartée.*")
        warnings.append(f"synthèse IA écartée, {outcome.fallback}.")
    empty = outcome.requested - len(outcome.qualifications)
    if outcome.model is not None and empty:
        warnings.append(f"{empty} qualification(s) suggérée(s) sur {outcome.requested} laissée(s) vide(s) par les "
                        "contrôles ou faute de réponse : motif dans le détail de chaque anomalie.")
    return text, note, warnings


def _paragraph(text: str) -> str:
    """A paragraph of the model as plain Markdown text: no heading, quote or list marker at the start."""
    if re.match(r"\d+[.)]\s", text):
        return re.sub(r"^(\d+)", r"\1\\", text, count=1)
    return "\\" + text if text and text[0] in "#>-*+|" else text


def run(workdir: Path, profile: Profile, thumbnails: bool | None = None, progress: Progress | None = None,
        ai: ai_mod.Options | None = None) -> Path:
    """``thumbnails``: True asked for (the source file is required), None by default (made if the
    source file is there, else left out with a note), False not made. ``ai``: the local model writes
    the synthesis and the qualifications (None: template synthesis, empty column)."""
    progress = progress or (lambda _msg: None)
    b = _Builder(workdir, profile)
    names: dict[int, str] = {}
    missing_source = None
    if thumbnails is not False:
        source = Path(b.probe.source.path)
        if not source.is_file():
            if thumbnails:
                raise ReportError(f"fichier source introuvable : {source} (nécessaire pour --thumbnails)")
            missing_source = source
            progress(f"Vignettes non produites : fichier source introuvable ({source})")
    if thumbnails is not False and missing_source is None:
        count = sum(e.type in VIDEO_TYPES and e.scope == "range" for e in b.events)
        progress(f"Vignettes : {count} anomalie(s) image")
        names = thumbs.make(source, b.probe.video.stream_index, b.events, b.m.video_settings,
                            workdir / wd.THUMBNAILS,
                            picture_of(b.probe.video.pix_fmt, b.probe.video.color_range, b.m.video_settings.matrix))
    outcome = None
    if ai is not None:
        context, items = b.ai_inputs()
        images = {n: workdir / wd.THUMBNAILS / name for n, name in names.items()}
        try:
            outcome = ai_mod.run(workdir, context, items, images, ai, progress)
        except Exception as exc:  # noqa: BLE001 - the report is always written (SPEC §8.1)
            outcome = ai_mod.failed(f"erreur de la couche IA ({exc.__class__.__name__} : {exc})")
        ai.outcome = outcome
    synthesis, synthesis_note, ai_warnings = synthesis_section(b.synthesis(), outcome)
    env = Environment(loader=FileSystemLoader(Path(__file__).parent), undefined=StrictUndefined,
                      keep_trailing_newline=True, autoescape=False)
    env.filters["cell"] = _cell
    sections = dict(
        h=b.header(),
        status=status_label(b.verdict.status, b.verdict.indicative, b.verdict.technical),
        score=number(b.verdict.score, 0 if b.verdict.score.is_integer() else 1),
        delivery=b.delivery(),
        synthesis=synthesis,
        synthesis_note=synthesis_note,
        ai_warnings=ai_warnings,
        checks=b.checks(),
        integrity_errors=b.integrity_errors(),
        audio=b.audio(),
        event_tables=b.event_tables(names, outcome),
        thumbnails=b.thumbnail_rows(names),
        thumbnails_note=(f"Vignettes non produites : fichier source introuvable ({missing_source})."
                         if missing_source else ""),
        charts=b.charts(),
        parameters=b.parameters(),
        norm_gaps=b.norm_gaps(),
        notes=b.notes(outcome),
    )
    text = env.get_template("rapport.md.j2").render(
        v=b.verdict, letterbox_changes=b.st.letterbox.changes if b.st.letterbox else [], **sections)
    md_path = workdir / wd.REPORT_MD
    md_path.write_text(text, encoding="utf-8", newline="\n")
    view = b.view(sections, names, outcome)
    (workdir / wd.REPORT_JSON).write_text(json.dumps(view, indent=2, ensure_ascii=False) + "\n", encoding="utf-8",
                                          newline="\n")
    progress("PDF")
    pdf.write(text, workdir, workdir / wd.REPORT_PDF, f"Rapport PAD Guard — {Path(b.probe.source.path).name}")
    return md_path
