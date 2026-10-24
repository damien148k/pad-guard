"""draft-profile: a draft broadcaster profile from the broadcaster's PDF (SPEC §13, Phase 4b)."""

from __future__ import annotations

from pathlib import Path

from pad_guard.draft import pdf
from pad_guard.draft.extract import DraftError, Extraction, Progress, extract
from pad_guard.draft.write import write_draft
from pad_guard.llm import LLMClient
from pad_guard.profiles.resolve import HOUSE, REPO_NORMS

ROOT = REPO_NORMS.parent
DRAFTS = ROOT / "profiles" / "drafts"

__all__ = ["DRAFTS", "DraftError", "make_draft", "proposed_extends"]


def proposed_extends(norms_dir: Path = REPO_NORMS) -> list[str]:
    """Every norm of normes/, the house rules last."""
    names = sorted(p.stem for p in norms_dir.glob("*.yaml") if p.stem != HOUSE)
    return names + ([HOUSE] if (norms_dir / f"{HOUSE}.yaml").is_file() else [])


def _shown(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def make_draft(pdf_path: Path, name: str, client: LLMClient, out_dir: Path = DRAFTS,
               broadcaster: str | None = None, progress: Progress | None = None,
               on_read=None) -> tuple[Extraction, dict[str, Path]]:
    try:
        doc = pdf.read(pdf_path)
    except pdf.PdfError as exc:
        raise DraftError(str(exc)) from None
    if on_read:
        on_read(doc)
    x = extract(doc, client, progress)
    meta = {
        "name": name,
        "version": "0.1",
        "broadcaster": broadcaster or name,
        "source_document": pdf_path.name,
        "notes": f"Brouillon extrait par {x.model} ({x.prompt_version}) : chaque valeur est à vérifier.",
        "extends": proposed_extends(),
        "status": "draft",
        "source_pdf": _shown(pdf_path),
        "source_pdf_sha256": doc.sha256,
    }
    return x, write_draft(out_dir, name, x, meta)
