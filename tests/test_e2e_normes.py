"""NORMES tab in a real browser (Playwright, Chromium headless): hidden without --admin; with it, the list, the
sheet of a norm, the page link to the PDF served locally, the « Signer » button enabled only once every row
is ticked, the signature written. Not run by default: ``uv run pytest -m e2e``."""

from __future__ import annotations

import shutil
import threading
import time

import pytest
import yaml

from pad_guard.draft import releve
from pad_guard.ui import server

from conftest import ROOT
from test_releve import ROWS, _survey, doc_pdf, lab  # noqa: F401  (fixtures)

pytestmark = [pytest.mark.e2e]

playwright = pytest.importorskip("playwright.sync_api")


def _serve(root, tmp_path, admin):
    import uvicorn

    sock = server._bind(0)
    port = sock.getsockname()[1]
    ctx = server.Context(token=server.secrets.token_urlsafe(16), hosts={f"127.0.0.1:{port}"},
                         settings_file=tmp_path / f"reglages{int(admin)}.json", root=root, admin=admin)
    srv = uvicorn.Server(uvicorn.Config(server.create_app(ctx), log_level="warning"))
    thread = threading.Thread(target=lambda: srv.run(sockets=[sock]), daemon=True)
    thread.start()
    while not srv.started:
        time.sleep(0.05)
    return srv, thread, f"http://127.0.0.1:{port}/"


@pytest.fixture
def root(lab):  # noqa: F811
    path = _survey(lab, ROWS)
    releve.run(path, lab / "normes", lab / "docs" / "normes", root=lab)
    shutil.copy(ROOT / "docs" / "VALEURS_MAISON.md", lab / "docs" / "VALEURS_MAISON.md")
    (lab / "profiles" / "drafts").mkdir(parents=True)
    return lab


def test_vincent_reads_and_signs_a_norm(root, tmp_path) -> None:
    errors, external = [], []
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Chromium de Playwright absent (uv run playwright install chromium) : {exc}")
        srv, thread, base = _serve(root, tmp_path, admin=False)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(base)
            page.get_by_role("button", name="Analyse", exact=True).wait_for()
            assert page.get_by_role("button", name="Normes", exact=True).count() == 0
        finally:
            srv.should_exit = True
            thread.join(10)

        srv, thread, base = _serve(root, tmp_path, admin=True)
        try:
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: m.type == "error" and errors.append(m.text))
            page.on("request", lambda r: not r.url.startswith(base) and external.append(r.url))
            page.goto(base)
            page.get_by_role("button", name="Normes", exact=True).click()
            row = page.locator(".norm-row", has_text="cst_rt099")
            row.wait_for()
            assert "à relire" in row.text_content() and "présent" in row.text_content()
            assert page.locator(".norm-row", has_text="Valeurs maison").count() == 1
            row.click()

            page.get_by_text("Renvois à d'autres normes").wait_for()
            link = page.get_by_role("link", name="p. 1")
            href = link.get_attribute("href")
            assert "/api/normes/cst_rt099/pdf" in href and href.endswith("#page=1")
            pdf = page.request.get(base.rstrip("/") + href.split("#")[0])
            assert pdf.ok and pdf.headers["content-type"] == "application/pdf"

            sign = page.get_by_role("button", name="Signer")
            page.get_by_label("Nom du validateur").fill("Vincent")
            boxes = page.locator(".nrow input[type=checkbox]")
            n = boxes.count()
            assert n == 3
            for i in range(n - 1):
                boxes.nth(i).check()
            assert sign.is_disabled()
            boxes.nth(n - 1).check()
            assert sign.is_enabled()
            sign.click()
            page.get_by_text("signée par Vincent le").first.wait_for()
            meta = yaml.safe_load((root / "normes" / "cst_rt099.yaml").read_text(encoding="utf-8"))["meta"]
            assert meta["validated_by"] == "Vincent"

            page.get_by_role("button", name="← Normes").click()
            assert "signée par Vincent" in page.locator(".norm-row", has_text="cst_rt099").text_content()
        finally:
            srv.should_exit = True
            thread.join(10)
            browser.close()
    assert errors == [] and external == []
