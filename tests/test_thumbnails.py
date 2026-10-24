"""Thumbnails on by default, and laid out in the PDF at their own size (never shrunk to fit a page)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import pymupdf
import pytest
from PIL import Image
from typer.testing import CliRunner

from pad_guard import workdir as wd
from pad_guard.cli import app
from pad_guard.report import pdf

from conftest import PROFILES, TEST_PROFILES

CLASSIC = TEST_PROFILES / "test_classic.yaml"
ARTE = PROFILES / "arte_hd_sdr.yaml"


def invoke(*args: str):
    return CliRunner().invoke(app, list(args))


def _images(path: Path) -> list[tuple[int, pymupdf.Rect]]:
    with pymupdf.open(path) as doc:
        return [(p.number, pymupdf.Rect(i["bbox"])) for p in doc for i in p.get_image_info()]


def test_pdf_never_shrinks_an_image(tmp_path) -> None:
    (tmp_path / "vignettes").mkdir()
    blocks = ["# Rapport", "Un paragraphe d'introduction.", "### Vignettes"]
    for k in range(1, 8):
        size = (1288, 360) if k % 3 == 0 else (640, 360)  # pictures, and pictures with their mask
        Image.fromarray(np.full((size[1], size[0], 3), 30 * k, np.uint8)).save(tmp_path / "vignettes" / f"v{k}.png")
        blocks += [f"**Anomalie {k}** — légende", f"![Anomalie {k}](vignettes/v{k}.png)"]
    blocks.append("## Annexe\n\nFin du rapport.")
    out = tmp_path / "rapport.pdf"
    pdf.write("\n\n".join(blocks) + "\n", tmp_path, out, "test")
    images = _images(out)
    assert len(images) == 7
    for page, rect in images:
        assert round(rect.width) == 480, (page, rect)
        assert round(rect.height) in (270, 134), (page, rect)  # 640x360 and 1288x360 at 480 points wide
        assert rect.y1 <= pdf.PAGE.height - pdf.MARGIN + 1
    with pymupdf.open(out) as doc:
        for page in doc:  # each caption is on the page of its image
            words = page.get_text()
            for k in range(1, 8):
                if f"Anomalie {k} " in words or f"Anomalie {k}\n" in words:
                    assert any(p == page.number for p, _ in images)
        grey = [d for page in doc for d in page.get_drawings()  # table header background, replayed on every page
                if d.get("fill") and all(abs(c - 0.91) < 0.01 for c in d["fill"])]
        assert grey == []


def test_blocks_keep_caption_with_image() -> None:
    parts = pdf.blocks("## Titre\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n**Anomalie 3** — x\n\nLégende.\n\n"
                       "![A](vignettes/a.png)\n\nSuite.\n")
    assert [keep for _, keep in parts] == [False, True, False]
    assert parts[1][0].startswith("**Anomalie 3**") and parts[1][0].endswith("![A](vignettes/a.png)")


@pytest.fixture(scope="module")
def default_runs(fixtures_dir, tmp_path_factory):
    runs = {}
    for name, profile in (("bad_levels.mov", CLASSIC), ("arte_bad.mov", ARTE)):
        out = tmp_path_factory.mktemp(name.replace(".", "_"))
        result = invoke("analyze", str(fixtures_dir / name), "--profile", str(profile), "--out", str(out))
        assert result.exception is None or isinstance(result.exception, SystemExit), result.output
        runs[name] = out
    return runs


def test_thumbnails_by_default(default_runs) -> None:
    out = default_runs["bad_levels.mov"]
    assert sorted(p.name for p in (out / wd.THUMBNAILS).iterdir()) == ["evenement_001.png", "evenement_002.png"]
    md = (out / wd.REPORT_MD).read_text(encoding="utf-8")
    assert "en rouge, Y au-dessus de la tolérance." in md and "en bleu, Y en dessous de la tolérance." in md
    assert "--thumbnails" not in json.loads((out / wd.RUN).read_text(encoding="utf-8"))["command"]
    for _, rect in _images(out / wd.REPORT_PDF):
        assert round(rect.width) == 480


def test_mask_legend_only_for_level_anomalies(default_runs) -> None:
    md = (default_runs["arte_bad.mov"] / wd.REPORT_MD).read_text(encoding="utf-8")
    section = md[md.index("### Vignettes"):md.index("## 7. Annexe")]
    assert "Mire présente" in section  # a picture anomaly, without a mask
    assert "pixels comptés" not in section


def test_no_thumbnails_option(fixtures_dir, tmp_path) -> None:
    out = tmp_path / "o"
    invoke("analyze", str(fixtures_dir / "bad_levels.mov"), "--profile", str(CLASSIC), "--out", str(out),
           "--no-thumbnails")
    assert not (out / wd.THUMBNAILS).exists() and "### Vignettes" not in (out / wd.REPORT_MD).read_text(encoding="utf-8")


def test_default_skips_thumbnails_without_source(default_runs, tmp_path) -> None:
    work = tmp_path / "copie"
    shutil.copytree(default_runs["bad_levels.mov"], work)
    shutil.rmtree(work / wd.THUMBNAILS)
    probe = json.loads((work / wd.PROBE).read_text(encoding="utf-8"))
    probe["source"]["path"] = str(tmp_path / "absent.mov")
    (work / wd.PROBE).write_text(json.dumps(probe, ensure_ascii=False), encoding="utf-8")
    result = invoke("report", str(work))
    assert result.exception is None or isinstance(result.exception, SystemExit), result.output
    assert "Vignettes non produites : fichier source introuvable" in (work / wd.REPORT_MD).read_text(encoding="utf-8")
    result = invoke("report", str(work), "--thumbnails")  # asked for explicitly: an error
    assert result.exit_code == 1 and "introuvable" in " ".join(result.output.split())
