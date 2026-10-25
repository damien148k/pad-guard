"""Phase 5 acceptance in a real browser (Playwright, Chromium headless): choose the film and the
profile, follow the analysis, read the verdict and the anomalies with their thumbnail, download
the PDF; the model of the local AI shown and chosen before a launch (a fake model list stands for
Ollama). Not run by default (marker e2e): ``uv run pytest -m e2e``; needs
``uv run playwright install chromium`` once."""

from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path

import pytest

from pad_guard.ui import server, settings as settings_mod

from conftest import ROOT, TEST_PROFILES

pytestmark = [pytest.mark.e2e, pytest.mark.fixtures]

playwright = pytest.importorskip("playwright.sync_api")


FAKE_MODELS = ["qwen3-vl:32b-instruct", "qwen3-vl:8b-instruct"]


@pytest.fixture
def running(tmp_path, fixtures_dir, monkeypatch):
    import uvicorn

    from pad_guard import llm

    # The server runs in this process: its model list (ollama list) is a fake one, Ollama is never called.
    monkeypatch.setattr(llm.OllamaClient, "installed", lambda self: list(FAKE_MODELS))

    root = tmp_path / "depot"
    (root / "profiles" / "drafts").mkdir(parents=True)
    shutil.copytree(ROOT / "normes", root / "normes", ignore=shutil.ignore_patterns("sources"))
    shutil.copyfile(TEST_PROFILES / "test_classic.yaml", root / "profiles" / "test_classic.yaml")
    sock = server._bind(0)
    port = sock.getsockname()[1]
    ctx = server.Context(token=server.secrets.token_urlsafe(16), hosts={f"127.0.0.1:{port}"},
                         settings_file=tmp_path / "reglages.json", root=root)
    settings_mod.save(settings_mod.Settings(analyses_root=str(tmp_path / "analyses")), ctx.settings_file)
    # The native Windows dialog cannot be driven by a test: the server's picker answers instead.
    ctx.extra["picker"] = lambda kind, initial: str(fixtures_dir / "bad_levels.mov") if kind == "master" else None
    srv = uvicorn.Server(uvicorn.Config(server.create_app(ctx), log_level="warning"))
    thread = threading.Thread(target=lambda: srv.run(sockets=[sock]), daemon=True)
    thread.start()
    while not srv.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/", tmp_path
    srv.should_exit = True
    thread.join(10)


def test_vincent_produces_a_report_without_a_terminal(running) -> None:
    base, tmp = running
    errors, external = [], []
    with playwright.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"Chromium de Playwright absent (uv run playwright install chromium) : {exc}")
        page = browser.new_page(viewport={"width": 1440, "height": 900}, accept_downloads=True)
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and errors.append(m.text))
        page.on("request", lambda r: not r.url.startswith(base) and external.append(r.url))
        page.goto(base)

        page.get_by_role("button", name="Parcourir…").first.click()
        page.get_by_text("bad_levels.mov", exact=True).wait_for()
        page.locator(".prof", has_text="test_classic").click()
        page.get_by_text("Format détecté").wait_for()
        page.get_by_role("button", name="Voir le récapitulatif →").click()
        page.get_by_text("Vérifiez avant de lancer l'analyse").wait_for()
        page.locator(".cmd", has_text="pad-guard analyze").wait_for()

        # Synthesis by the local AI: the model used is shown before the launch, chosen among those installed.
        synthesis = page.get_by_role("checkbox")
        synthesis.check()
        picker = page.get_by_label("Modèle de l'IA locale")
        picker.wait_for()
        assert picker.input_value() == "qwen3-vl:8b-instruct"  # the default model, preselected
        assert page.locator("select option").all_inner_texts() == ["qwen3-vl:32b-instruct", "qwen3-vl:8b-instruct (défaut)"]
        page.locator(".cmd", has_text="--llm ollama --llm-model qwen3-vl:8b-instruct").wait_for()
        picker.select_option("qwen3-vl:32b-instruct")
        page.locator(".cmd", has_text="--llm-model qwen3-vl:32b-instruct").wait_for()
        synthesis.uncheck()  # the analysis itself runs without the model (the CLI would call the real Ollama)
        assert picker.count() == 0
        page.wait_for_function("() => !document.querySelector('.cmd').textContent.includes('--llm')")
        page.get_by_role("button", name="Lancer l'analyse").click()

        page.locator(".stage", has_text="Mesures image").wait_for()
        report = page.get_by_role("button", name="Voir le rapport")
        page.wait_for_function("() => [...document.querySelectorAll('button')].some(b => b.textContent === 'Voir le rapport' && !b.disabled)",
                               timeout=180_000)
        assert page.locator(".stage.done").count() == 6
        report.click()

        page.locator(".verdict .word").wait_for()
        assert page.locator(".verdict .word").inner_text() == "NON-CONFORME"
        assert page.locator(".rows .row").count() == 2  # bad_levels.mov: the two events of the Phase 3 acceptance
        page.locator(".rows .row").first.click()
        img = page.locator(".detail .thumb img")
        img.wait_for()
        page.wait_for_function("() => { const i = document.querySelector('.detail .thumb img'); return i && i.naturalWidth > 0; }")
        page.wait_for_function("() => location.hash.includes('&a=')")  # the anomaly is named by its key in the link
        assert "%40" in page.url.split("&a=")[1]  # type@frame@group, not a rank

        with page.expect_download() as dl:
            page.get_by_role("link", name="Télécharger le PDF").click()
        saved = Path(tmp / "telecharge.pdf")
        dl.value.save_as(saved)
        assert saved.read_bytes()[:5] == b"%PDF-"

        # New draft from a PDF: same choice of model, shown before « Extraire » (not started here).
        page.get_by_role("button", name="Profils").click()
        draft_picker = page.get_by_label("Modèle de l'IA locale")
        draft_picker.wait_for()
        assert draft_picker.input_value() == "qwen3-vl:8b-instruct"
        draft_picker.select_option("qwen3-vl:32b-instruct")
        assert draft_picker.input_value() == "qwen3-vl:32b-instruct"
        browser.close()
    assert errors == [] and external == []  # nothing loaded from the Internet
