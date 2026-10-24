"""Phase 5: the local interface (pad-guard ui). The server computes nothing about the verdict; these
tests check what it serves, its local protections, and that the page needs no network."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from pad_guard.ui import server

from conftest import ROOT

TOKEN = "jeton-de-test"


@pytest.fixture
def ctx(tmp_path) -> server.Context:
    return server.Context(token=TOKEN, hosts={"testserver"}, settings_file=tmp_path / "reglages.json")


@pytest.fixture
def client(ctx):
    with TestClient(server.create_app(ctx), headers={"X-PAD-Guard": TOKEN}) as c:
        yield c


def test_page_carries_token_and_policy(client) -> None:
    r = client.get("/")
    assert r.status_code == 200 and f'content="{TOKEN}"' in r.text
    csp = r.headers["content-security-policy"]
    assert "default-src 'self'" in csp and "script-src 'self'" in csp and "connect-src 'self'" in csp
    assert r.headers["x-content-type-options"] == "nosniff"
    js = client.get("/static/app.js")
    assert js.status_code == 200 and js.headers["content-type"].startswith("text/javascript")


def test_api_needs_the_session_token(ctx) -> None:
    with TestClient(server.create_app(ctx)) as c:
        assert c.get("/api/profiles").status_code == 403
        assert c.get("/api/profiles", headers={"X-PAD-Guard": "faux"}).status_code == 403
        assert c.get(f"/api/profiles?t={TOKEN}").status_code == 200
        assert c.get("/api/ping").json()["app"] == "pad-guard"  # no token: tells another instance it runs


def test_foreign_host_and_origin_are_refused(ctx, client) -> None:
    with TestClient(server.create_app(ctx), base_url="http://evil.example", headers={"X-PAD-Guard": TOKEN}) as c:
        assert c.get("/").status_code == 403  # DNS rebinding: the Host is not ours
    r = client.post("/api/settings", headers={"Origin": "http://evil.example"}, json={})
    assert r.status_code == 403 and "origine" in r.json()["error"]
    assert client.get("/api/settings", headers={"Origin": "http://testserver"}).status_code == 200


def test_server_listens_on_localhost_only() -> None:
    assert server.HOST == "127.0.0.1"
    sock = server._bind(0)
    try:
        assert sock.getsockname()[0] == "127.0.0.1"
    finally:
        sock.close()


def test_no_network_resource_in_the_page() -> None:
    """Every script, style, font and image is a local file: no CDN, no Google Fonts at run time."""
    namespaces = {"http://www.w3.org/2000/svg", "http://www.w3.org/1999/xlink"}
    for path in server.STATIC.rglob("*"):
        if path.suffix not in (".js", ".css", ".html", ".svg"):
            continue
        found = set(re.findall(r"https?://[^\s\"'`)]+", path.read_text(encoding="utf-8"))) - namespaces
        assert not found, f"{path.name} : {found}"
        assert "@import" not in path.read_text(encoding="utf-8"), path.name
    css = (server.STATIC / "fonts.css").read_text(encoding="utf-8")
    for font in re.findall(r"url\((fonts/[^)]+)\)", css):
        assert (server.STATIC / font).is_file(), font
    licences = {p.name for p in (server.STATIC / "fonts").glob("LICENSE-*.txt")}
    assert licences == {"LICENSE-barlow.txt", "LICENSE-barlow-condensed.txt", "LICENSE-ibm-plex-mono.txt"}
    assert (server.STATIC / "vendor" / "LICENSE-preact.txt").is_file()


def test_profiles_as_their_files_say(client) -> None:
    data = client.get("/api/profiles").json()
    arte = next(p for p in data["profiles"] if p["name"] == "arte_hd_sdr")
    assert arte["status"] == "validated" and arte["broadcaster"] and arte["version"]
    assert arte["file"] == "profiles/arte_hd_sdr.yaml"
    assert {d["name"] for d in data["drafts"]} >= {"arte_hd_sdr"}


def test_settings_root_outside_the_repository(client, tmp_path) -> None:
    default = client.get("/api/settings").json()
    assert default["analyses_root"].endswith(str(Path("Documents") / "PAD Guard" / "analyses"))
    assert "chemin complet" in client.put("/api/settings", json={"analyses_root": "relatif"}).json()["error"]
    inside = client.put("/api/settings", json={"analyses_root": str(ROOT / "out")})
    assert inside.status_code == 400 and "dépôt" in inside.json()["error"]
    root = tmp_path / "analyses"
    assert client.put("/api/settings", json={"analyses_root": str(root)}).json()["analyses_root"] == str(root)
    assert root.is_dir() and client.get("/api/settings").json()["analyses_root"] == str(root)
