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


# --- Dépôt and Récapitulatif --------------------------------------------------------------------

import shutil  # noqa: E402

import pdf_fixture  # noqa: E402
from conftest import TEST_PROFILES  # noqa: E402


@pytest.fixture
def lab(tmp_path) -> server.Context:
    """A repository of its own: profiles/ (Arte and the classic test profile) and normes/."""
    root = tmp_path / "depot"
    (root / "profiles" / "drafts").mkdir(parents=True)
    shutil.copytree(ROOT / "normes", root / "normes", ignore=shutil.ignore_patterns("sources"))
    shutil.copyfile(ROOT / "profiles" / "arte_hd_sdr.yaml", root / "profiles" / "arte_hd_sdr.yaml")
    shutil.copyfile(TEST_PROFILES / "test_classic.yaml", root / "profiles" / "test_classic.yaml")
    return server.Context(token=TOKEN, hosts={"testserver"}, settings_file=tmp_path / "reglages.json", root=root)


@pytest.fixture
def lab_client(lab):
    with TestClient(server.create_app(lab), headers={"X-PAD-Guard": TOKEN}) as c:
        yield c


def test_pick_returns_a_path_never_the_file(lab, lab_client) -> None:
    asked = []
    lab.extra["picker"] = lambda kind, initial: asked.append((kind, initial)) or r"D:\Masters\film.mov"
    assert lab_client.post("/api/pick", json={"kind": "master"}).json() == {"path": r"D:\Masters\film.mov"}
    lab_client.post("/api/pick", json={"kind": "pdf"})
    assert asked[-1] == ("pdf", str(lab.root / "diffuseurs"))
    assert lab_client.post("/api/pick", json={"kind": "autre"}).status_code == 400


def test_file_info(lab_client, tmp_path) -> None:
    assert "chemin complet" in lab_client.post("/api/file-info", json={"path": "film.mov"}).json()["error"]
    assert "introuvable" in lab_client.post("/api/file-info", json={"path": str(tmp_path / "x.mov")}).json()["error"]
    film = tmp_path / "Film.MOV"
    film.write_bytes(b"0" * 1000)
    info = lab_client.post("/api/file-info", json={"path": f'"{film}"'}).json()
    assert info["name"] == "Film.MOV" and info["size_bytes"] == 1000 and info["supported_extension"]


def test_profile_summary_cites_the_client(lab_client) -> None:
    s = lab_client.get("/api/profiles/arte_hd_sdr/summary").json()
    loud = next(r for r in s["requirements"] if r["label"] == "Loudness intégrée")
    assert loud["value"] == "-23,0 LUFS ± 1,0 LU" and loud["ref"].startswith("Arte §3.3.2.4")
    assert [g["name"] for g in s["groups"]] == ["VO", "VF", "VI"] and "EBU R 128" in s["norms"]
    assert lab_client.get("/api/profiles/..%5Cx/summary").status_code == 400


@pytest.mark.fixtures
def test_probe_preview_and_audio_map(lab_client, fixtures_dir) -> None:
    pv = lab_client.post("/api/probe-preview", json={"path": str(fixtures_dir / "arte_4tracks.mov"),
                                                     "profile": "arte_hd_sdr"}).json()
    assert pv["accepted"] and pv["tracks"] == [1, 2, 3, 4]
    assert dict(pv["key_cells"])["Codec"] == "prores HQ"
    assert pv["assign"] == {"1": "VO", "2": "VO", "3": "VF", "4": "VF"}  # the profile's own map
    same = lab_client.post("/api/audio-map", json={"profile": "arte_hd_sdr", "assign": pv["assign"], "tracks": 4}).json()
    # VI (tracks 5-6) is absent from the file: the map is given explicitly, as for the real Arte master.
    assert same["spec"] == "VO:1-2,VF:3-4" and same["describe"] == "VO 1-2, VF 3-4"
    other = lab_client.post("/api/audio-map", json={"profile": "arte_hd_sdr", "tracks": 4,
                                                    "assign": {"1": "VF", "2": "VF", "3": "VO", "4": "VO"}}).json()
    assert other["spec"] == "VO:3-4,VF:1-2"
    mono = lab_client.post("/api/audio-map", json={"profile": "arte_hd_sdr", "tracks": 4,
                                                   "assign": {"1": "VO", "2": None, "3": "VF", "4": "VF"}}).json()
    assert mono["spec"] == "VO:1,VF:3-4"  # one track: mono, as audio_map decides
    absent = lab_client.post("/api/audio-map", json={"profile": "arte_hd_sdr", "tracks": 4, "assign": {"5": "VO"}})
    assert absent.status_code == 400 and "absente" in absent.json()["error"]
    assert lab_client.post("/api/audio-map", json={"profile": "arte_hd_sdr", "tracks": 4,
                                                   "assign": {"1": "XX"}}).status_code == 400


def test_pdf_match_by_fingerprint(lab, lab_client, tmp_path) -> None:
    doc = pdf_fixture.make(tmp_path / "chaine.pdf")
    r = lab_client.post("/api/pdf-match", json={"path": str(doc)}).json()
    assert r["pages"] == 3 and len(r["sha256"]) == 64 and r["profiles"] == []
    arte = lab.root / "profiles" / "arte_hd_sdr.yaml"
    text = arte.read_text(encoding="utf-8")
    sha = next(line.split(":")[1].strip().strip('"') for line in text.splitlines() if line.strip().startswith("source_pdf_sha256:"))
    arte.write_text(text.replace(sha, r["sha256"]), encoding="utf-8")
    again = lab_client.post("/api/pdf-match", json={"path": str(doc)}).json()
    assert [p["name"] for p in again["profiles"]] == ["arte_hd_sdr"]
    other = tmp_path / "note.txt"
    other.write_text("x", encoding="utf-8")
    assert lab_client.post("/api/pdf-match", json={"path": str(other)}).status_code == 400
