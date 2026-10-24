"""rapport.md -> rapport.pdf, locally: markdown-it-py renders HTML, PyMuPDF lays it out on A4 pages.

No network and no system library (WeasyPrint needs GTK on Windows). Images are read from the
analysis directory through a PyMuPDF archive.

PyMuPDF shrinks an image to fit the room left at the bottom of a page. An image is evidence (a
thumbnail of an anomaly, a chart) and must keep its size: each image is laid out as one block
with the short paragraphs and heading just before it (its caption, its legend), and the block
goes to the next page when it does not fit. Text between images flows across pages as usual.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import pymupdf
from markdown_it import MarkdownIt

CSS = """
body { font-family: sans-serif; font-size: 9pt; line-height: 1.3; }
h1 { font-size: 16pt; margin: 0 0 6pt 0; }
h2 { font-size: 12.5pt; margin: 12pt 0 4pt 0; border-bottom: 0.5pt solid #888; }
h3 { font-size: 10.5pt; margin: 8pt 0 3pt 0; }
p, li { margin: 2pt 0; }
table { border-collapse: collapse; margin: 4pt 0; width: 100%; }
th, td { border: 0.5pt solid #999; padding: 1.5pt 2.5pt; vertical-align: top; font-size: 7.5pt; }
th { font-weight: bold; text-align: left; border-bottom: 1pt solid #555; }
code { font-family: monospace; font-size: 7.5pt; }
img { width: 480px; border: 0.5pt solid #888; }
"""

PAGE = pymupdf.paper_rect("a4")
MARGIN = 36  # points (12.7 mm)
GAP = 4  # points between two blocks
CAPTION_BLOCKS = 3  # paragraphs or heading kept with the image that follows them
_IMAGE = re.compile(r"^\s*!\[[^\]]*\]\([^)]*\)\s*$")


_CODE = re.compile(r"<code>(.*?)</code>", re.S)
MAX_PAGES_PER_BLOCK = 200  # a block that still does not fit is a layout error, not a long report


def _breakable(match: re.Match) -> str:
    # A long path or command line has no space to break at: a table cell holding it would be wider
    # than the page and PyMuPDF would never place it. A zero-width space after each separator lets
    # the line break there, without changing the text read.
    return "<code>" + re.sub(r"([\\/_.=-])", "\\1\u200b", match.group(1)) + "</code>"


def to_html(markdown: str) -> str:
    body = MarkdownIt("commonmark", {"html": False}).enable("table").render(markdown)
    return f"<html><body>{_CODE.sub(_breakable, body)}</body></html>"


def _is_caption(block: str) -> bool:
    """A heading or a short paragraph (not a table, not a list) that introduces the next image."""
    first = block.lstrip()
    return bool(first) and not first.startswith(("|", "- ", "* ")) and not _IMAGE.match(block) \
        and len(block.splitlines()) <= 3


def blocks(markdown: str) -> list[tuple[str, bool]]:
    """(markdown, keep together) parts: every image with its caption is one block kept together."""
    out: list[tuple[str, bool]] = []
    flow: list[str] = []
    for block in re.split(r"\n[ \t]*\n", markdown):
        if not _IMAGE.match(block):
            flow.append(block)
            continue
        keep = [block]
        while flow and len(keep) <= CAPTION_BLOCKS and _is_caption(flow[-1]):
            keep.insert(0, flow.pop())
        if flow:
            out.append(("\n\n".join(flow), False))
            flow = []
        out.append(("\n\n".join(keep), True))
    if flow:
        out.append(("\n\n".join(flow), False))
    return out


class _Pages:
    """Pages written one after the other; ``y`` is where the next block starts."""

    def __init__(self, writer: pymupdf.DocumentWriter):
        self.writer = writer
        self.device = None
        self.area = PAGE + (MARGIN, MARGIN, -MARGIN, -MARGIN)
        self.y = self.area.y1  # no page yet: as if the last one were full

    def new(self) -> None:
        if self.device is not None:
            self.writer.end_page()
        self.device = self.writer.begin_page(PAGE)
        self.y = self.area.y0

    def room(self) -> pymupdf.Rect:
        return pymupdf.Rect(self.area.x0, self.y, self.area.x1, self.area.y1)

    def close(self) -> None:
        if self.device is not None:
            self.writer.end_page()


def _height(html: str, archive: pymupdf.Archive, width: float) -> float:
    story = pymupdf.Story(html=html, user_css=CSS, archive=archive)
    _, filled = story.place(pymupdf.Rect(0, 0, width, 100_000))
    return pymupdf.Rect(filled).height


def write(markdown: str, base_dir: Path, path: Path, title: str) -> int:
    """Write the PDF; returns the number of pages."""
    archive = pymupdf.Archive(str(base_dir))
    buffer = io.BytesIO()
    pages = _Pages(pymupdf.DocumentWriter(buffer))
    for text, keep in blocks(markdown):
        html = to_html(text)
        if keep and _height(html, archive, pages.area.width) > pages.room().height:
            pages.new()  # the image keeps its size: next page
        story = pymupdf.Story(html=html, user_css=CSS, archive=archive)
        more = True
        for _ in range(MAX_PAGES_PER_BLOCK):
            if not more:
                break
            if pages.device is None or pages.room().height < 2 * GAP:
                pages.new()
            more, filled = story.place(pages.room())
            story.draw(pages.device)
            pages.y = pymupdf.Rect(filled).y1 + GAP
            if more:
                pages.new()
        if more:
            raise ValueError(f"rapport.pdf : un bloc du rapport ne tient pas dans la page ({text[:80]!r}…)")
    pages.close()
    pages.writer.close()

    doc = pymupdf.open(stream=buffer.getvalue(), filetype="pdf")
    count = doc.page_count
    for i, page in enumerate(doc, start=1):
        page.insert_text((MARGIN, PAGE.height - MARGIN / 2), f"{title} — page {i}/{count}", fontsize=7,
                         color=(0.4, 0.4, 0.4))
    doc.set_metadata({"title": title, "producer": "PAD Guard", "creator": "PAD Guard"})
    doc.save(str(path), garbage=3, deflate=True)
    doc.close()
    return count
