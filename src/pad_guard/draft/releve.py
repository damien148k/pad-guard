"""releve-norme: a norm surveyed by hand from its PDF, checked by the code, and its review table.

The survey (``normes/releves/<name>.yaml``) lists, for each value the norm writes, the field of the
profile, the value, the page and the quote. Every row goes through the checks of draft-profile
(``extract.check``: the quote is in its page, it speaks of the field, it holds the number, the
table column fits): one refused row and nothing is written. Rows « non retenues » record what the
norm says without a value of PAD Guard (a field it does not fix, a parameter internal to PAD
Guard), their quote checked the same way.

The output is the norm (``normes/<name>.yaml``, every value with its page and quote) and the table
that Vincent reads and signs (``docs/normes/<name>.md``). For a norm that profiles already use and
whose file must not change (``fichier_norme: verifier``), the survey is compared with the file:
same fields, same values, and only the table is written. A norm that fixes no value of the profile (a
measurement method, a report) gets its table alone (``fichier_norme: aucun``): no empty file in normes/.
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from pad_guard.draft import glossary as glossary_mod
from pad_guard.draft import pdf as pdf_mod
from pad_guard.draft import signature
from pad_guard.draft import verify
from pad_guard.draft.extract import OK, check
from pad_guard.draft.schema import catalogue
from pad_guard.draft.write import dump
from pad_guard.profiles.resolve import _norm_chain, leaves, load_norm, read_yaml
from pad_guard.rules.profile import ProfileError

ROOT = Path(__file__).resolve().parents[3]
DOCS = ROOT / "docs" / "normes"


class ReleveError(Exception):
    """The survey cannot be used. The message is user-facing (French)."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Row(_Model):
    champ: str
    valeur: Any = None
    page: int
    citation: str
    remarque: str = ""
    pdf: str | None = None  # key of autres_pdf when the quote is in another document
    # citation: only the quote is checked (a free text value, a list of words); never for a number.
    # code10: a percentage of the legal range the norm writes as 10-bit code values (R 103: « 20 - 984 »):
    # the code the rules apply (rounded outward, measure.video.pct_to_code) must be in the quote.
    controle: Literal["complet", "citation", "code10"] = "complet"


class Unused(_Model):
    sujet: str  # a field of the profile, or what the norm speaks of
    page: int
    citation: str
    remarque: str
    pdf: str | None = None


class OtherPdf(_Model):
    fichier: str
    libelle: str


class Survey(_Model):
    meta: dict[str, Any]
    libelle: str  # how the sources name the document: « CST-RT-040 V1.2, 2016 »
    fichier_norme: Literal["ecrire", "verifier", "aucun"] = "ecrire"
    releve_par: str
    releve_le: dt.date
    autres_pdf: dict[str, OtherPdf] = {}
    valeurs: list[Row] = Field(default_factory=list)
    non_retenus: list[Unused] = Field(default_factory=list)
    absents: str = ""  # one sentence: what the norm does not fix


@dataclass
class Checked:
    row: Row
    source: str  # the « sources » line of the norm


def load(path: Path) -> Survey:
    try:
        survey = Survey.model_validate(read_yaml(path))
    except ProfileError as exc:
        raise ReleveError("\n".join(exc.messages)) from None
    except ValidationError as exc:
        raise ReleveError("relevé invalide :\n  - " + "\n  - ".join(
            f"{'.'.join(map(str, e['loc']))} : {e['msg']}" for e in exc.errors())) from None
    if survey.meta.get("name") != path.stem:
        raise ReleveError(f"meta.name doit être « {path.stem} » (nom du fichier)")
    if survey.fichier_norme == "aucun" and survey.valeurs:
        raise ReleveError("fichier_norme: aucun, mais le relevé a des valeurs : choisir « ecrire »")
    return survey


def _documents(survey: Survey, root: Path) -> dict[str | None, tuple[pdf_mod.Document, str]]:
    """PDF of each row (None: the norm's own PDF) and how its sources name it."""
    wanted = {None: (survey.meta.get("source_pdf"), survey.libelle)}
    wanted.update({k: (o.fichier, o.libelle) for k, o in survey.autres_pdf.items()})
    out = {}
    for key, (name, label) in wanted.items():
        if not name:
            raise ReleveError("meta.source_pdf manque : le relevé se vérifie dans le PDF de la norme")
        path = root / name
        if not path.is_file():
            raise ReleveError(f"PDF introuvable : {name} (normes/sources/ n'est pas versionné, voir son README.md)")
        out[key] = (pdf_mod.read(path), label)
    return out


def verify_rows(survey: Survey, root: Path = ROOT, glossary: glossary_mod.Glossary | None = None,
                docs: dict | None = None) -> list[Checked]:
    """Every row checked against its page; ReleveError lists all the refused rows. ``docs``: the PDFs already
    read (_documents), when the rows are checked one by one."""
    docs = docs if docs is not None else _documents(survey, root)
    specs = {s.path: s for s in catalogue()}
    glossary = glossary if glossary is not None else glossary_mod.load()
    errors, out = [], []
    seen: set[str] = set()
    for row in survey.valeurs:
        where = f"{row.champ} (p. {row.page})"
        if row.pdf not in docs:
            errors.append(f"{where} : pdf « {row.pdf} » absent de autres_pdf")
            continue
        doc, label = docs[row.pdf]
        if row.champ in seen:
            errors.append(f"{where} : champ relevé deux fois")
            continue
        seen.add(row.champ)
        if row.controle == "citation":
            why = _quote_only(doc, row.page, row.citation, row.valeur, specs.get(row.champ) is None)
        elif row.controle == "code10":
            why = _code10(doc, row)
        else:
            f = check(doc, {"field": row.champ, "value": row.valeur, "page": row.page, "quote": row.citation},
                      specs, 0, [row.page], glossary)
            why = None if f.status == OK else f"{f.status} : {f.reason}"
        if why:
            errors.append(f"{where} : {why}")
            continue
        out.append(Checked(row, f"{label} p. {row.page} : « {' '.join(row.citation.split())} »"))
    for u in survey.non_retenus:
        if u.pdf not in docs:
            errors.append(f"non retenu {u.sujet} : pdf « {u.pdf} » absent de autres_pdf")
            continue
        why = _quote_only(docs[u.pdf][0], u.page, u.citation, None, False)
        if why:
            errors.append(f"non retenu {u.sujet} (p. {u.page}) : {why}")
    if errors:
        raise ReleveError("relevé refusé, rien n'a été écrit :\n  - " + "\n  - ".join(errors))
    return out


_PCT_SIDE = {"video.y_tolerance_low_pct": "low", "video.rgb_min_pct": "low",
             "video.y_tolerance_high_pct": "high", "video.rgb_max_pct": "high"}
LEGAL_10BIT = (64, 940)  # BT.709 §4.6, R 103 table 1: the base of the profile percentages (SPEC §5.2)


def _code10(doc: pdf_mod.Document, row: Row) -> str | None:
    from pad_guard.measure.video import pct_to_code

    side = _PCT_SIDE.get(row.champ)
    if side is None or not isinstance(row.valeur, (int, float)) or isinstance(row.valeur, bool):
        return "controle: code10 ne vaut que pour un pourcentage de niveau vidéo"
    why = _quote_only(doc, row.page, row.citation, None, False)
    if why:
        return why
    code = pct_to_code(row.valeur, LEGAL_10BIT, side)
    if verify.value_in_quote(code, row.citation):
        return f"la citation ne contient pas le code 10 bits {code} ({row.valeur:g} %)"
    return None


def _quote_only(doc: pdf_mod.Document, number: int, quote: str, value: Any, unknown: bool) -> str | None:
    if unknown:
        return "champ inconnu du profil"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return "un nombre se vérifie toujours en entier (controle: complet)"
    page = doc.page(number)
    if page is None:
        return f"page {number} absente du document ({len(doc.pages)} pages)"
    if verify.quote_in(quote, page.full_text) or verify.table_row(quote, page.tables):
        return None
    elsewhere = [p.number for p in doc.pages if p.number != number and verify.quote_in(quote, p.full_text)]
    return "citation introuvable dans la page" + (f" (trouvée p. {elsewhere[0]})" if elsewhere else "")


def _set(data: dict, path: str, value: Any) -> None:
    *parents, last = path.split(".")
    for p in parents:
        data = data.setdefault(p, {})
    data[last] = value


def build_norm(survey: Survey, rows: list[Checked], root: Path = ROOT) -> dict[str, Any]:
    data: dict[str, Any] = {}
    sources = {}
    for c in rows:
        _set(data, c.row.champ, c.row.valeur)
        sources[c.row.champ] = c.source
    meta: dict[str, Any] = {"kind": "norm"}
    for key, value in survey.meta.items():
        if key in signature.SIGNATURE_KEYS:
            continue
        meta[key] = value
        if key == "source_pdf":
            meta["source_pdf_sha256"] = pdf_mod.sha256(root / value)
    # A new norm is never signed: Vincent reads the new table, then signer-norme.
    meta["validated_by"] = None
    meta["validated_at"] = None
    return {"meta": meta, **data, "sources": dict(sorted(sources.items()))}


def write_norm(survey: Survey, rows: list[Checked], survey_path: Path, norms_dir: Path,
               root: Path = ROOT) -> Path:
    """normes/<name>.yaml, checked (schema, a source for every value, the norms it extends) before it replaces the file."""
    data = build_norm(survey, rows, root)
    out = norms_dir / f"{survey.meta['name']}.yaml"
    tmp = norms_dir / ".releve" / out.name  # same file name: meta.name must match it
    tmp.parent.mkdir(parents=True, exist_ok=True)
    d = data["meta"]["document"]
    header = [f"Norme {survey.meta['name']} écrite par pad-guard releve-norme depuis {_shown(survey_path, root)}.",
              f"Document : {d['title']} ({d['version']}), {data['meta']['source_pdf']} "
              f"(SHA-256 {data['meta']['source_pdf_sha256']}).",
              f"Relevé par {survey.releve_par} le {survey.releve_le.isoformat()} ; chaque citation a été retrouvée "
              "par le code dans sa page, avec son nombre.",
              f"Tableau de relecture : docs/normes/{survey.meta['name']}.md. Ne pas modifier à la main : corriger "
              "le relevé et relancer pad-guard releve-norme."]
    tmp.write_text(dump(data, None, header), encoding="utf-8", newline="\n")
    try:
        norm = load_norm(tmp)
        _norm_chain(norm.meta.extends, norms_dir, f"normes/{norm.name}.yaml", [norm.name], {}, [], tmp)
    except ProfileError as exc:
        tmp.unlink(missing_ok=True)
        raise ReleveError("norme invalide, rien n'a été écrit :\n  - " + "\n  - ".join(exc.messages)) from None
    tmp.replace(out)
    tmp.parent.rmdir()
    return out


def compare_with_norm(survey: Survey, rows: list[Checked], norm_path: Path) -> None:
    """fichier_norme: verifier. The norm file keeps its text; the survey must give exactly its values."""
    norm = load_norm(norm_path)
    raw = read_yaml(norm_path)
    raw.pop("meta", None)
    raw.pop("sources", None)
    in_file = dict(leaves(raw))
    surveyed = {c.row.champ: c.row.valeur for c in rows}
    errors = []
    for path, value in in_file.items():
        if path not in surveyed:
            errors.append(f"{path} : dans {norm_path.name} ({json.dumps(value, ensure_ascii=False)}), absent du relevé")
        elif _canonical(surveyed[path]) != _canonical(value):
            errors.append(f"{path} : {norm_path.name} dit {json.dumps(value, ensure_ascii=False)}, "
                          f"le relevé {json.dumps(surveyed[path], ensure_ascii=False)}")
    errors += [f"{p} : relevé ({json.dumps(v, ensure_ascii=False)}), absent de {norm_path.name}"
               for p, v in surveyed.items() if p not in in_file]
    if norm.name != survey.meta.get("name"):
        errors.append(f"meta.name : {norm.name} dans {norm_path.name}")
    if errors:
        raise ReleveError(f"le relevé et {norm_path.name} diffèrent (fichier_norme: verifier, rien n'a été écrit) :\n  - "
                          + "\n  - ".join(errors))


def _canonical(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        value = list(value)
    if isinstance(value, int) and not isinstance(value, bool):
        value = float(value)
    return json.dumps(value, sort_keys=True)


def _shown(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.name


def _cell(text: Any) -> str:
    text = text if isinstance(text, str) else json.dumps(text, ensure_ascii=False)
    return " ".join(text.split()).replace("|", "\\|")


HOW_TO_READ = [
    "> **Comment relire** (la signature ne porte que sur ce tableau)",
    ">",
    "> 1. Pour chaque ligne, ouvrir le PDF de la norme (dossier `normes\\sources\\`) à la page indiquée et comparer "
    "la valeur à la citation.",
    "> 2. Dans la colonne « OK / correction », écrire `OK`, ou noter la correction (valeur juste, page, citation).",
    "> 3. Un champ absent du tableau n'est pas contrôlé par cette norme.",
    "> 4. Une correction se fait par `releve-norme` (ligne modifiée avec sa citation), puis nouvelle relecture.",
    "> 5. Signer : `uv run pad-guard signer-norme <nom> --par \"Vincent\"` (refusé si la norme a changé depuis "
    "ce tableau).",
]


def table(survey: Survey, rows: list[Checked], survey_path: Path, root: Path = ROOT,
          norm_sha: str | None = None) -> str:
    """The review table, in French, for Vincent: one line per value, then what the norm says without a value."""
    m = survey.meta
    d = m["document"]
    specs = {s.path: s.description for s in catalogue()}
    pdf_path = root / m["source_pdf"]
    lines = [f"# {d['title']} ({d['version']}) : relevé des valeurs", "",
             *[ln.replace("<nom>", m["name"]) for ln in HOW_TO_READ], "",
             f"Document : `{m['source_pdf']}` (SHA-256 `{pdf_mod.sha256(pdf_path)}`).",
             *[f"Autre document cité : `{o.fichier}` ({o.libelle})." for o in survey.autres_pdf.values()],
             f"Relevé par {survey.releve_par} le {survey.releve_le.strftime('%d/%m/%Y')} : "
             f"`{_shown(survey_path, root)}`.",
             _norm_line(survey.fichier_norme, m["name"]),
             *([signature.stamp_line(m["name"], norm_sha)] if norm_sha else []), "",
             "Chaque citation a été retrouvée par `pad-guard releve-norme` dans la page indiquée ; pour une valeur "
             "chiffrée, le nombre est dans la citation, et dans un tableau la colonne correspond au champ. "
             "Le code ne juge pas du sens : c'est l'objet de cette relecture.", ""]
    refs = m.get("refers_to") or []
    if refs:
        lines += ["## Normes auxquelles ce document renvoie", "",
                  "Leurs valeurs s'appliquent aussi quand un diffuseur renvoie à ce document (renvoi transitif) ; "
                  "elles ne sont pas recopiées ici.", "",
                  f"| Norme | Citation du renvoi | Version citée | {signature.CHECK_COLUMN} |", "|---|---|---|---|"]
        lines += [f"| `{r['norm']}` | {_cell(r['source'])} | {_cell(r.get('cited_version') or '')} | |" for r in refs]
        lines.append("")
    lines += ["## Valeurs", "", f"| Champ | Valeur | Page | Citation | Remarque | {signature.CHECK_COLUMN} |",
              "|---|---|---|---|---|---|"]
    for c in rows:
        r = c.row
        name = f"`{r.champ}`" + (f"<br>{_cell(specs[r.champ])}" if specs.get(r.champ) else "")
        page = f"{r.page}" + (f" ({survey.autres_pdf[r.pdf].libelle})" if r.pdf else "")
        note = r.remarque + {"citation": " Valeur en texte libre : seule la citation est vérifiée par le code.",
                             "code10": " Pourcentage écrit en code 10 bits par la norme : le code vérifie le code "
                                       "équivalent (arrondi vers l'extérieur) dans la citation."}.get(r.controle, "")
        lines.append(f"| {name} | `{_cell(r.valeur)}` | {page} | « {_cell(r.citation)} » | {_cell(note.strip())} | |")
    if not rows:
        lines.append("| (aucune) | | | | | |")
    lines.append("")
    if survey.non_retenus:
        lines += ["## Lu dans la norme, sans valeur dans PAD Guard", "",
                  f"| Sujet | Page | Citation | Pourquoi aucune valeur | {signature.CHECK_COLUMN} |",
                  "|---|---|---|---|---|"]
        for u in survey.non_retenus:
            page = f"{u.page}" + (f" ({survey.autres_pdf[u.pdf].libelle})" if u.pdf else "")
            lines.append(f"| {_cell(u.sujet)} | {page} | « {_cell(u.citation)} » | {_cell(u.remarque)} | |")
        lines.append("")
    if survey.absents:
        lines += ["## Champs absents", "", survey.absents, ""]
    sign = (f"puis `uv run pad-guard signer-norme {m['name']} --par \"Vincent\"` écrit la signature dans "
            f"`normes/{m['name']}.yaml`." if norm_sha else
            "aucune valeur n'est appliquée par PAD Guard : ce tableau se lit, rien n'est à signer.")
    lines += ["## Validation", "",
              "Pour chaque ligne : la valeur correspond-elle au sens du document ? Corrections dans le relevé "
              f"(`{_shown(survey_path, root)}`), puis `uv run pad-guard releve-norme {_shown(survey_path, root)}`, "
              f"qui réécrit ce tableau et efface la signature ; relecture complète, {sign}", "",
              signature.unsigned_line(), ""]
    return "\n".join(lines)


def _norm_line(mode: str, name: str) -> str:
    if mode == "ecrire":
        return f"Norme écrite à partir de ce relevé : `normes/{name}.yaml`."
    if mode == "verifier":
        return f"Norme comparée à ce relevé (mêmes champs, mêmes valeurs ; fichier inchangé) : `normes/{name}.yaml`."
    return "Aucune valeur du profil : pas de fichier dans `normes/`."


def run(survey_path: Path, norms_dir: Path, docs_dir: Path = DOCS, root: Path = ROOT) -> tuple[Path | None, Path]:
    """Check the survey, then write the norm (or compare it) and the table. Returns (norm written or None, table)."""
    survey = load(survey_path)
    rows = verify_rows(survey, root)
    norm_path = norms_dir / f"{survey.meta['name']}.yaml"
    written = None
    if survey.fichier_norme == "verifier":
        compare_with_norm(survey, rows, norm_path)
        signature.clear(norm_path)  # a new table: a new signature
    elif survey.fichier_norme == "ecrire":
        written = write_norm(survey, rows, survey_path, norms_dir, root)
    norm_sha = signature.norm_fingerprint(norm_path) if survey.fichier_norme != "aucun" else None
    docs_dir.mkdir(parents=True, exist_ok=True)
    out = docs_dir / f"{survey.meta['name']}.md"
    out.write_text(table(survey, rows, survey_path, root, norm_sha), encoding="utf-8", newline="\n")
    return written, out
