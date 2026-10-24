"""Read a broadcaster PDF: text per page (tables included) and page images (SPEC §13).

pdfplumber gives the text and the tables; pypdfium2 renders the pages that hold a table or
little text, for the vision model. The PDF is opened read-only and never modified; its SHA-256
is recorded. PyMuPDF is not used here (AGPL licence, CLAUDE.md).
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field
from pathlib import Path

LOW_TEXT_CHARS = 200  # a page with less text than this is rendered for the vision model
RENDER_SCALE = 1.25  # 90 dpi: enough to read a table, few image tokens


class PdfError(Exception):
    """The PDF cannot be read. The message is user-facing (French)."""


@dataclass
class Page:
    number: int  # 1-based, as printed by PDF viewers
    text: str  # pdfplumber text of the page
    tables: list[list[list[str]]] = field(default_factory=list)  # rows of cells

    @property
    def tables_text(self) -> str:
        """Tables as lines « cell | cell | cell »."""
        return "\n".join(" | ".join(cell for cell in row) for table in self.tables for row in table)

    @property
    def full_text(self) -> str:
        """Everything the model is shown for this page, and everything a quote may be found in."""
        return self.text + ("\n" + self.tables_text if self.tables else "")

    @property
    def needs_image(self) -> bool:
        return bool(self.tables) or len(self.text.strip()) < LOW_TEXT_CHARS

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())


@dataclass
class Document:
    path: Path
    sha256: str
    pages: list[Page]

    def page(self, number: int) -> Page | None:
        return self.pages[number - 1] if 1 <= number <= len(self.pages) else None


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(1 << 20):
            h.update(block)
    return h.hexdigest()


def read(path: Path) -> Document:
    import pdfplumber

    if not path.is_file():
        raise PdfError(f"PDF introuvable : {path}")
    try:
        with pdfplumber.open(path) as pdf:
            pages = []
            for i, p in enumerate(pdf.pages, start=1):
                tables = [[[(cell or "").replace("\n", " ").strip() for cell in row] for row in table]
                          for table in p.extract_tables()]
                pages.append(Page(number=i, text=p.extract_text() or "", tables=[t for t in tables if t]))
    except Exception as exc:  # noqa: BLE001 - pdfminer raises many kinds of errors on a bad file
        raise PdfError(f"PDF illisible ({exc.__class__.__name__}) : {path}") from None
    return Document(path=path, sha256=sha256(path), pages=pages)


def render(path: Path, number: int, scale: float = RENDER_SCALE) -> bytes:
    """PNG image of page ``number`` (1-based)."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(path))
    try:
        image = pdf[number - 1].render(scale=scale).to_pil()
    finally:
        pdf.close()
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()
