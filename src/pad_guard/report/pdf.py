"""rapport.md -> rapport.pdf, locally: markdown-it-py renders HTML, PyMuPDF lays it out on A4 pages.

No network and no system library (WeasyPrint needs GTK on Windows). Images are read from the
analysis directory through a PyMuPDF archive.
"""

from __future__ import annotations

import io
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
th { background-color: #e8e8e8; text-align: left; }
code { font-family: monospace; font-size: 7.5pt; }
img { width: 480px; border: 0.5pt solid #888; }
"""

PAGE = pymupdf.paper_rect("a4")
MARGIN = 36  # points (12.7 mm)


def to_html(markdown: str) -> str:
    body = MarkdownIt("commonmark", {"html": False}).enable("table").render(markdown)
    return f"<html><body>{body}</body></html>"


def write(markdown: str, base_dir: Path, path: Path, title: str) -> int:
    """Write the PDF; returns the number of pages."""
    story = pymupdf.Story(html=to_html(markdown), user_css=CSS, archive=pymupdf.Archive(str(base_dir)))
    buffer = io.BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    where = PAGE + (MARGIN, MARGIN, -MARGIN, -MARGIN)
    more = True
    while more:
        device = writer.begin_page(PAGE)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
    writer.close()

    doc = pymupdf.open(stream=buffer.getvalue(), filetype="pdf")
    pages = doc.page_count
    for i, page in enumerate(doc, start=1):
        page.insert_text((MARGIN, PAGE.height - MARGIN / 2), f"{title} — page {i}/{pages}", fontsize=7,
                         color=(0.4, 0.4, 0.4))
    doc.set_metadata({"title": title, "producer": "PAD Guard", "creator": "PAD Guard"})
    doc.save(str(path), garbage=3, deflate=True)
    doc.close()
    return pages
