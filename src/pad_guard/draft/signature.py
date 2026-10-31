"""signer-norme: Vincent's signature of a review table, written into the norm it covers.

A review table (``docs/normes/<name>.md``, or ``docs/VALEURS_MAISON.md`` for ``lumiris_maison``) carries
the fingerprint of the norm file at the time it was generated (``STAMP`` line). Signing checks that the
norm has not changed since (its content, without the signature itself), that no row of the table holds
a correction still to make, then writes ``validated_by``, ``validated_at`` and ``validated_table_sha256``
(fingerprint of the table as read, without its « Relu par » line) into ``meta`` of the norm, and fills the
« Relu par … le … » line of the table. The signature covers that table only.

A correction never goes through the signature: ``releve-norme`` (the row changed with its quote), which
writes a new table and erases the signature, then a new signature.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pad_guard.profiles.resolve import read_yaml
from pad_guard.rules.profile import ProfileError

HOUSE = "lumiris_maison"
SIGNATURE_KEYS = ("validated_by", "validated_at", "validated_table_sha256")
CHECK_COLUMN = "OK / correction"
SIGNED_LINE = "Relu par"
_STAMP_RE = re.compile(r"^Empreinte de `normes/([\w.-]+)\.yaml` à la génération de ce tableau : `([0-9a-f]{64})`\.$",
                       re.M)
_OK = {"ok", "✓", "✔", "x"}


class SignatureError(Exception):
    """The table cannot be signed. The message is user-facing (French)."""


def table_path(name: str, root: Path) -> Path:
    return root / "docs" / "VALEURS_MAISON.md" if name == HOUSE else root / "docs" / "normes" / f"{name}.md"


def norm_fingerprint(path: Path) -> str:
    """SHA-256 of the norm's content (values, sources, meta), its signature excluded: comments do not count."""
    try:
        data = read_yaml(path)
    except ProfileError as exc:
        raise SignatureError("\n".join(exc.messages)) from None
    meta = dict(data.get("meta") or {})
    for key in SIGNATURE_KEYS:
        meta.pop(key, None)
    data = {**data, "meta": meta}
    text = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def stamp_line(name: str, fingerprint: str) -> str:
    return f"Empreinte de `normes/{name}.yaml` à la génération de ce tableau : `{fingerprint}`."


def unsigned_line() -> str:
    return f"{SIGNED_LINE} : ____________________  le : ____________"


def table_fingerprint(text: str) -> str:
    """SHA-256 of the table as read (« OK / correction » cells included), its « Relu par » line excluded."""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")
             if not line.startswith(SIGNED_LINE)]
    return hashlib.sha256("\n".join(lines).strip().encode("utf-8")).hexdigest()


def _cells(line: str) -> list[str]:
    body = line.strip()[1:-1] if line.strip().endswith("|") else line.strip()[1:]
    return [c.strip() for c in re.split(r"(?<!\\)\|", body)]


def pending_corrections(text: str) -> list[str]:
    """Rows whose « OK / correction » cell holds something else than OK: a correction still to make."""
    out, column, header = [], None, None
    for line in text.split("\n"):
        if not line.lstrip().startswith("|"):
            column = None
            continue
        cells = _cells(line)
        if column is None:
            column = cells.index(CHECK_COLUMN) if CHECK_COLUMN in cells else -1
            header = True
            continue
        if header:  # |---|---|
            header = False
            continue
        if column >= 0 and column < len(cells):
            cell = cells[column]
            if cell and cell.lower().rstrip(".") not in _OK:
                out.append(f"{cells[0]} : « {cell} »")
    return out


@dataclass
class Status:
    signed: bool
    by: str | None
    at: dt.date | None
    problems: list[str]  # empty: the signature still covers the table and the norm


def _meta(path: Path) -> dict[str, Any]:
    try:
        return dict(read_yaml(path).get("meta") or {})
    except ProfileError as exc:
        raise SignatureError("\n".join(exc.messages)) from None


def _check_table(name: str, norm: Path, table: Path) -> tuple[str, list[str]]:
    """The table text and why it no longer matches the norm file (empty: it does)."""
    if not table.is_file():
        raise SignatureError(f"tableau de relecture introuvable : {table}")
    text = table.read_text(encoding="utf-8")
    m = _STAMP_RE.search(text)
    if m is None or m.group(1) != name:
        hint = ("relancer pad-guard releve-norme" if name != HOUSE
                else "mettre à jour la ligne « Empreinte » du tableau (test_signature donne la valeur)")
        return text, [f"{table.name} ne porte pas l'empreinte de normes/{name}.yaml : {hint}"]
    current = norm_fingerprint(norm)
    if m.group(2) != current:
        how = (f"relancer pad-guard releve-norme normes/releves/{name}.yaml" if name != HOUSE
               else f"mettre à jour {table.name} (lignes et empreinte)")
        return text, [f"normes/{name}.yaml a changé depuis la génération du tableau : le tableau relu ne "
                      f"correspond plus au fichier ; {how}, relire, puis signer"]
    return text, []


def status(name: str, root: Path) -> Status:
    norm = root / "normes" / f"{name}.yaml"
    meta = _meta(norm)
    by, at, sha = (meta.get(k) for k in SIGNATURE_KEYS)
    if not by:
        return Status(False, None, None, [])
    at = dt.date.fromisoformat(str(at)) if at else None
    text, problems = _check_table(name, norm, table_path(name, root))
    if sha != table_fingerprint(text):
        problems.append(f"{table_path(name, root).name} a changé depuis la signature")
    return Status(True, by, at, problems)


def sign(name: str, by: str, root: Path, today: dt.date | None = None) -> tuple[Path, Path]:
    """Write the signature into normes/<name>.yaml and the « Relu par » line of the table."""
    by = " ".join(by.split())
    if not by:
        raise SignatureError("--par : le nom de la personne qui a relu est obligatoire")
    norm = root / "normes" / f"{name}.yaml"
    if not norm.is_file():
        survey = root / "normes" / "releves" / f"{name}.yaml"
        if survey.is_file():
            raise SignatureError(f"{name} ne fixe aucune valeur de PAD Guard (pas de normes/{name}.yaml) : "
                                 "son tableau se lit, rien n'est à signer")
        raise SignatureError(f"norme inconnue : normes/{name}.yaml n'existe pas")
    table = table_path(name, root)
    text, problems = _check_table(name, norm, table)
    if problems:
        raise SignatureError("signature refusée, rien n'a été écrit :\n  - " + "\n  - ".join(problems))
    pending = pending_corrections(text)
    if pending:
        how = ("par pad-guard releve-norme (ligne modifiée avec sa citation)" if name != HOUSE
               else f"dans normes/{HOUSE}.yaml et {table.name}")
        raise SignatureError(f"signature refusée : corrections notées dans le tableau, à faire d'abord {how}, "
                             "puis nouvelle signature :\n  - " + "\n  - ".join(pending))
    today = today or dt.date.today()
    fingerprint = table_fingerprint(text)
    write_signature(norm, {"validated_by": by, "validated_at": today,
                           "validated_table_sha256": fingerprint})
    line = (f"{SIGNED_LINE} {by} le {today.strftime('%d/%m/%Y')} (pad-guard signer-norme ; empreinte du tableau "
            f"`{fingerprint}`, écrite dans `normes/{name}.yaml`).")
    lines = text.split("\n")
    idx = [i for i, ln in enumerate(lines) if ln.startswith(SIGNED_LINE)]
    if idx:
        lines[idx[-1]] = line
    else:
        lines[-1:] = [lines[-1], line, ""] if lines[-1] else [line, ""]
    table.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return norm, table


def clear(norm: Path) -> str | None:
    """Erase the signature of a norm (new table: a new signature is needed). Returns who had signed."""
    if not norm.is_file():
        return None
    who = _meta(norm).get("validated_by")
    if who or any(k in _meta(norm) for k in SIGNATURE_KEYS[2:]):
        write_signature(norm, {"validated_by": None, "validated_at": None})
    return who


def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, dt.date):
        return value.isoformat()
    return json.dumps(value, ensure_ascii=False)


def write_signature(norm: Path, values: dict[str, Any]) -> None:
    """Set the signature keys at the end of the top-level ``meta`` block, comments of the file kept."""
    lines = norm.read_text(encoding="utf-8").split("\n")
    try:
        start = lines.index("meta:")
    except ValueError:
        raise SignatureError(f"{norm.name} : bloc meta: introuvable") from None
    end = start + 1
    while end < len(lines) and (not lines[end].strip() or lines[end].startswith(" ")):
        end += 1
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    block = [ln for ln in lines[start + 1:end]
             if not any(ln.startswith(f"  {k}:") for k in SIGNATURE_KEYS)]
    block += [f"  {k}: {_scalar(v)}" for k, v in values.items()]
    lines[start + 1:end] = block
    before = norm.read_text(encoding="utf-8")
    norm.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    try:
        from pad_guard.profiles.resolve import load_norm

        load_norm(norm)
    except ProfileError as exc:
        norm.write_text(before, encoding="utf-8", newline="\n")
        raise SignatureError("norme invalide après signature, rien n'a été écrit :\n  - "
                             + "\n  - ".join(exc.messages)) from None
