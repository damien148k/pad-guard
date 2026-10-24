"""draft-profile: a draft broadcaster profile from the broadcaster's PDF (SPEC §13, Phase 4b)."""

from __future__ import annotations

from pathlib import Path

from pad_guard.draft import examples, glossary, pdf
from pad_guard.draft.extract import Context, DraftError, Extraction, Progress, extract
from pad_guard.draft.write import write_draft
from pad_guard.llm import LLMClient
from pad_guard.profiles.resolve import HOUSE, REPO_NORMS, is_norm, read_yaml

ROOT = REPO_NORMS.parent
DRAFTS = ROOT / "profiles" / "drafts"
PROFILES = ROOT / "profiles"

__all__ = ["DRAFTS", "DraftError", "make_draft", "proposed_extends"]


def available_norms(norms_dir: Path = REPO_NORMS) -> list[str]:
    """International norms of normes/ (files with meta.kind: norm), the house rules excepted."""
    return sorted(p.stem for p in norms_dir.glob("*.yaml") if p.stem != HOUSE and is_norm(read_yaml(p)))


def proposed_extends(cited: list[str] | None = None, norms_dir: Path = REPO_NORMS) -> list[str]:
    """Every norm of normes/, those the document refers to after the others (the later wins),
    the house rules last."""
    names = available_norms(norms_dir)
    cited = [n for n in cited or [] if n in names]
    return [n for n in names if n not in cited] + cited + ([HOUSE] if (norms_dir / f"{HOUSE}.yaml").is_file() else [])


def _shown(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(path.resolve())


def make_draft(pdf_path: Path, name: str, client: LLMClient, out_dir: Path = DRAFTS,
               broadcaster: str | None = None, progress: Progress | None = None,
               on_read=None, glossary_path: Path = glossary.GLOSSARY,
               profiles_dir: Path = PROFILES) -> tuple[Extraction, dict[str, Path]]:
    try:
        doc = pdf.read(pdf_path)
        terms = glossary.load(glossary_path)
    except (pdf.PdfError, glossary.GlossaryError) as exc:
        raise DraftError(str(exc)) from None
    if on_read:
        on_read(doc)
    target = examples.Target(name=name, broadcaster=broadcaster, pdf_sha256=doc.sha256, pdf_name=pdf_path.name)
    context = Context(glossary=terms, examples=examples.collect(profiles_dir, target))
    x = extract(doc, client, progress, context=context)
    meta = {
        "name": name,
        "version": "0.1",
        "broadcaster": broadcaster or name,
        "source_document": pdf_path.name,
        "notes": f"Brouillon extrait par {x.model} ({x.prompt_version}) : chaque valeur est à vérifier.",
        "extends": proposed_extends(list(x.cited_norms())),
        "status": "draft",
        "source_pdf": _shown(pdf_path),
        "source_pdf_sha256": doc.sha256,
    }
    available = set(available_norms())
    norms = {key: (terms.normes[key].titre if key in terms.normes else key, key in available, f)
             for key, f in x.cited_norms().items()}
    return x, write_draft(out_dir, name, x, meta, norms)
