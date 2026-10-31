"""Changes to a norm made from the NORMES tab of the interface, always through the code of releve-norme.

- ``correct``: one row of the survey (value, page, quote) changed, the whole survey checked again in its PDF
  (``releve.verify_rows``: refused if the quote is not on the page, or lacks the number), then the norm and its
  table written again (``releve.run``): the signature is erased, a new one is needed.
- ``survey_from_draft``: the proposals of the local AI (``draft-profile --kind norme``) become a survey, each row
  checked like a hand survey; a refused row is left out and counted. Then the same sheet as any norm.
- ``set_info``: domain, region, superseded_by in ``meta`` (norm and survey): information, never a value, the
  signature stays valid.

A norm compared with its survey (``fichier_norme: verifier``, inherited by Arte) is never changed here.
"""

from __future__ import annotations

import datetime as dt
import json
import tempfile
from pathlib import Path
from typing import Any

import yaml

from pad_guard.draft import releve, signature
from pad_guard.draft.extract import OK

MAX_INFO = 120


# Said with every correction the PDF does not bear out (decision of Vincent, 31/10/2026: a stricter
# requirement than the norm is a house value, the norm stays as written).
STRICTER = ("La fiche d'une norme reprend le texte du PDF ; pour une exigence plus stricte, utiliser les valeurs "
            "maison (normes/lumiris_maison.yaml, docs/VALEURS_MAISON.md).")


def _paths(name: str, root: Path) -> tuple[Path, Path]:
    return root / "normes" / "releves" / f"{name}.yaml", root / "normes" / f"{name}.yaml"


def _items(lines: list[str], list_key: str) -> tuple[list[tuple[int, int]], str]:
    """(start, end) of each item of the top-level list ``list_key`` (comments between items left outside), and
    the indentation of its items (« - » or «   - »)."""
    try:
        top = lines.index(f"{list_key}:")
    except ValueError:
        return [], ""
    first = next((ln for ln in lines[top + 1:] if ln.lstrip().startswith("- ")), "- ")
    indent = first[:len(first) - len(first.lstrip())]
    starts, end = [], len(lines)
    for i in range(top + 1, len(lines)):
        line = lines[i]
        if line.startswith(indent + "- "):
            starts.append(i)
        elif line.strip() and not line.startswith(" ") and not line.startswith("#"):
            end = i
            break
    spans = []
    for k, start in enumerate(starts):
        stop = starts[k + 1] if k + 1 < len(starts) else end
        while stop > start + 1 and (not lines[stop - 1].strip() or lines[stop - 1].lstrip().startswith("#")):
            stop -= 1
        spans.append((start, stop))
    return spans, indent


def replace_item(text: str, list_key: str, index: int, item: dict) -> str:
    lines = text.split("\n")
    spans, indent = _items(lines, list_key)
    if index >= len(spans):
        raise releve.ReleveError(f"ligne introuvable dans le relevé ({list_key} n° {index + 1})")
    dumped = yaml.safe_dump([item], allow_unicode=True, sort_keys=False, width=10**6).rstrip("\n").split("\n")
    start, stop = spans[index]
    lines[start:stop] = [indent + ln for ln in dumped]
    return "\n".join(lines)


def _checked_text(survey_path: Path, text: str, root: Path) -> releve.Survey:
    """The survey ``text`` loaded and every row checked in its PDF, before anything is written."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / survey_path.name
        tmp_path.write_text(text, encoding="utf-8", newline="\n")
        survey = releve.load(tmp_path)
    releve.verify_rows(survey, root)
    return survey


def _one_line(text: Any, what: str) -> str:
    out = " ".join(str(text or "").split())
    if not out:
        raise releve.ReleveError(f"{what} vide")
    return out


def correct(name: str, key: str, valeur: str | None, page: Any, citation: str, root: Path,
            today: dt.date | None = None) -> Path:
    """One row corrected; returns the new review table. ReleveError says why it is refused (nothing written)."""
    survey_path, _ = _paths(name, root)
    if not survey_path.is_file():
        raise releve.ReleveError(f"pas de relevé pour {name} (normes/releves/{name}.yaml) : rien à corriger ici")
    survey = releve.load(survey_path)
    if survey.fichier_norme == "verifier":
        raise releve.ReleveError(f"{name} est comparée à son relevé (fichier_norme: verifier) : profils hérités, "
                                 f"dont Arte. Correction à la main dans normes/{name}.yaml, avec contrôle "
                                 "d'explain-profile Arte, puis releve-norme.")
    try:
        page = int(page)
    except (TypeError, ValueError):
        raise releve.ReleveError(f"page illisible : {page}") from None
    if page < 1:
        raise releve.ReleveError(f"page illisible : {page}")
    citation = _one_line(citation, "citation")
    stamp = f"Corrigé le {(today or dt.date.today()).strftime('%d/%m/%Y')} dans l'interface."
    kind, _, ref = key.partition(":")
    if kind == "v":
        index = next((i for i, r in enumerate(survey.valeurs) if r.champ == ref), None)
        if index is None:
            raise releve.ReleveError(f"champ absent du relevé : {ref}")
        text_value = _one_line(valeur, "valeur")
        try:
            value = yaml.safe_load(text_value)
        except yaml.YAMLError:
            value = text_value
        row = survey.valeurs[index]
        item = row.model_dump(exclude_defaults=True) | {"valeur": value, "page": page, "citation": citation,
                                                         "remarque": f"{row.remarque} {stamp}".strip()}
        item = {"champ": row.champ, **{k: v for k, v in item.items() if k != "champ"}}
        list_key = "valeurs"
    elif kind == "n":
        try:
            index = int(ref)
            row = survey.non_retenus[index]
        except (ValueError, IndexError):
            raise releve.ReleveError(f"ligne inconnue : {key}") from None
        item = row.model_dump(exclude_defaults=True) | {"page": page, "citation": citation,
                                                         "remarque": f"{row.remarque} {stamp}".strip()}
        list_key = "non_retenus"
    else:
        raise releve.ReleveError("seules les valeurs et les lignes « lu dans la norme » se corrigent ici")
    text = replace_item(survey_path.read_text(encoding="utf-8"), list_key, index, item)
    try:
        _checked_text(survey_path, text, root)
    except releve.ReleveError as exc:
        raise releve.ReleveError(str(exc).replace("relevé refusé", "correction refusée") + "\n" + STRICTER) from None
    survey_path.write_text(text, encoding="utf-8", newline="\n")
    _, table = releve.run(survey_path, root / "normes", root / "docs" / "normes", root)
    return table


def clean_info(values: dict[str, Any]) -> dict[str, str | None]:
    out = {}
    for key in signature.INFO_KEYS:
        text = " ".join(str(values.get(key) or "").split())
        if len(text) > MAX_INFO:
            raise releve.ReleveError(f"{key} : {MAX_INFO} caractères au plus")
        out[key] = text or None
    return out


def set_info(name: str, values: dict[str, Any], root: Path) -> None:
    """Domain, region, superseded_by into meta of the norm (and of its survey, which writes the norm again)."""
    info = clean_info(values)
    kept = {k: v for k, v in info.items() if v is not None}
    survey_path, norm = _paths(name, root)
    if not norm.is_file():
        raise releve.ReleveError(f"norme introuvable : normes/{name}.yaml")
    if survey_path.is_file():
        text = signature.meta_text(survey_path.read_text(encoding="utf-8"), kept, signature.INFO_KEYS,
                                   survey_path.name)
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / survey_path.name).write_text(text, encoding="utf-8", newline="\n")
            releve.load(Path(tmp) / survey_path.name)
        survey_path.write_text(text, encoding="utf-8", newline="\n")
    try:
        signature.write_meta(norm, kept, signature.INFO_KEYS)
    except signature.SignatureError as exc:
        raise releve.ReleveError(str(exc)) from None


def drafts(root: Path) -> list[dict]:
    """Norm drafts of the local AI (normes/drafts/) that have no survey nor norm yet."""
    out = []
    for path in sorted((root / "normes" / "drafts").glob("*.findings.json")):
        name = path.name.removesuffix(".findings.json")
        survey_path, norm = _paths(name, root)
        if survey_path.exists() or norm.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        doc = (data.get("meta") or {}).get("document") or {}
        out.append({"name": name, "title": doc.get("title"), "version": doc.get("version"),
                    "model": data.get("model"), "proposals": sum(f.get("status") == OK for f in data.get("fields", []))})
    return out


def survey_from_draft(name: str, root: Path, today: dt.date | None = None) -> tuple[Path, int, list[str]]:
    """The AI's proposals as a survey, every row checked; returns (survey, rows kept, proposals left out)."""
    survey_path, norm = _paths(name, root)
    findings = root / "normes" / "drafts" / f"{name}.findings.json"
    if not findings.is_file():
        raise releve.ReleveError(f"brouillon introuvable : normes/drafts/{name}.findings.json")
    if survey_path.exists() or norm.exists():
        raise releve.ReleveError(f"{name} existe déjà (normes/releves/ ou normes/) : rien n'est remplacé")
    data = json.loads(findings.read_text(encoding="utf-8"))
    meta = data.get("meta") or {}
    model = data.get("model") or "?"
    doc = meta.get("document") or {}
    if not meta.get("source_pdf") or not doc.get("title"):
        raise releve.ReleveError("brouillon sans PDF ou sans titre : relancer le relevé IA")
    source = Path(meta["source_pdf"])
    if source.is_absolute() and source.resolve().is_relative_to(root.resolve()):
        meta["source_pdf"] = source.resolve().relative_to(root.resolve()).as_posix()
    remark = f"Proposé par l'IA locale ({model}) ; citation vérifiée par le code, sens à vérifier."
    rows, dropped = [], []
    for f in data.get("fields", []):
        x = next((x for x in f.get("findings", []) if x.get("status") == OK), None)
        if f.get("status") != OK or x is None:
            dropped.append(f"{f.get('path')} : {f.get('status')}")
            continue
        rows.append(releve.Row(champ=f["path"], valeur=x["value"], page=x["page"], citation=x["quote"],
                               remarque=remark))
    cited = sorted({c.get("title") or c.get("norm") for c in data.get("cited_norms", []) if c.get("norm")})
    survey = releve.Survey(
        meta={"name": name, "document": {"title": doc["title"], "version": doc.get("version") or "?"},
              "source_pdf": meta["source_pdf"], "extends": [], "refers_to": [], "applies": "on_reference",
              "notes": f"Relevé proposé par l'IA locale ({model}) depuis le PDF : chaque ligne est à relire."},
        libelle=f"{doc['title'].split(' — ')[0]} ({doc.get('version') or '?'})", fichier_norme="ecrire",
        releve_par=f"IA locale {model} (draft-profile --kind norme), citations vérifiées par releve-norme",
        releve_le=today or dt.date.today(), valeurs=rows)
    docs = releve._documents(survey, root)  # noqa: SLF001 - one reading of the PDF for all the rows
    kept = []
    for row in rows:
        try:
            releve.verify_rows(survey.model_copy(update={"valeurs": [row]}), root, docs=docs)
            kept.append(row)
        except releve.ReleveError as exc:
            dropped.append(f"{row.champ} : {str(exc).splitlines()[-1].strip(' -')}")
    absents = (f"Relevé proposé par l'IA locale ({model}) : {len(dropped)} proposition(s) écartée(s) (statut de "
               f"draft-profile ou citation refusée), voir normes/drafts/{name}.findings.json.")
    if cited:
        absents += f" Normes citées par le document, renvois non repris (à confirmer) : {', '.join(cited)}."
    survey = survey.model_copy(update={"valeurs": kept, "absents": absents,
                                       "fichier_norme": "ecrire" if kept else "aucun"})
    dumped = survey.model_dump(exclude_defaults=False, mode="json")
    dumped["valeurs"] = [r.model_dump(exclude_defaults=True) for r in kept]
    dumped.pop("autres_pdf", None)
    dumped.pop("non_retenus", None)
    header = (f"# Relevé de {doc['title']} proposé par l'IA locale ({model}) depuis l'interface (onglet NORMES),\n"
              "# chaque citation vérifiée par releve-norme ; le sens de chaque ligne reste à relire.\n\n")
    survey_path.parent.mkdir(parents=True, exist_ok=True)
    survey_path.write_text(header + yaml.safe_dump(dumped, allow_unicode=True, sort_keys=False, width=10**6),
                           encoding="utf-8", newline="\n")
    try:
        releve.run(survey_path, root / "normes", root / "docs" / "normes", root)
    except Exception:
        survey_path.unlink(missing_ok=True)
        raise
    return survey_path, len(kept), dropped
