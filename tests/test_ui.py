"""Phase 5: the local interface (pad-guard ui). The server computes nothing about the verdict; these
tests check what it serves, its local protections, and that the page needs no network."""

from __future__ import annotations

import json
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


# --- background analysis ------------------------------------------------------------------------


from pad_guard import workdir as wd  # noqa: E402
from pad_guard.ui import jobs as jobs_mod  # noqa: E402


@pytest.fixture
def analyses(lab, lab_client, tmp_path) -> Path:
    root = tmp_path / "analyses"
    lab_client.put("/api/settings", json={"analyses_root": str(root)})
    return root


@pytest.mark.fixtures
def test_analysis_runs_the_cli_in_the_background(lab, lab_client, analyses, fixtures_dir) -> None:
    film = fixtures_dir / "bad_levels.mov"
    body = {"master": str(film), "profile": "test_classic", "audio_map": None, "llm": False}
    plan = lab_client.post("/api/jobs/analyze/preview", json=body).json()
    assert plan["problems"] == [] and plan["command"].startswith("pad-guard analyze ")
    assert Path(plan["workdir"]).parent == analyses and re.fullmatch(r"bad_levels_\d{8}-\d{4}", Path(plan["workdir"]).name)
    first = lab_client.post("/api/jobs/analyze", json=body).json()
    assert first["state"] == "running" and first["kind"] == "analyze"
    second = lab_client.post("/api/jobs/analyze", json=body)
    assert second.status_code == 409 and "déjà en cours" in second.json()["error"]  # one job at a time
    job = lab.extra["jobs"].wait()
    snap = lab_client.get("/api/jobs/current").json()
    assert job.state == "done" and snap["state"] == "done" and snap["exit_code"] == 4
    assert snap["result"]["status"] == "NON-CONFORME" and snap["pct"] == 100.0
    assert [s["state"] for s in snap["stages"]] == ["done"] * 6
    assert snap["journal"][-1]["msg"] == "terminé · verdict calculé par les règles : NON-CONFORME"
    work = Path(snap["workdir"])
    run = json.loads((work / wd.RUN).read_text(encoding="utf-8"))
    assert run["command"].startswith("pad-guard analyze") and run["finished_at"]
    assert (work / wd.REPORT_JSON).is_file() and (work / wd.REPORT_PDF).is_file()
    assert json.loads((work / "ui_job.json").read_text(encoding="utf-8"))["state"] == "done"
    # The stream sends the final state then closes.
    with lab_client.stream("GET", "/api/jobs/current/events") as r:
        data = [line for line in r.iter_lines() if line.startswith("data: ")]
    assert json.loads(data[-1][6:])["state"] == "done"


@pytest.mark.fixtures
def test_cancel_kills_the_whole_analysis(lab, lab_client, analyses, fixtures_dir) -> None:
    body = {"master": str(fixtures_dir / "arte_4tracks.mov"), "profile": "arte_hd_sdr",
            "audio_map": "VO:1-2,VF:3-4", "llm": False}
    started = lab_client.post("/api/jobs/analyze", json=body).json()
    pid = lab.extra["jobs"].current().pid
    snap = lab_client.post("/api/jobs/current/cancel").json()
    assert started["state"] == "running" and snap["state"] == "cancelled"
    for _ in range(50):
        if not jobs_mod.pid_alive(pid):
            break
        import time

        time.sleep(0.1)
    assert not jobs_mod.pid_alive(pid)
    assert "annulé" in snap["journal"][-1]["msg"]
    assert not (Path(snap["workdir"]) / wd.VERDICT).exists()


def test_job_found_again_after_a_restart(tmp_path) -> None:
    directory = tmp_path / "taches"
    directory.mkdir()
    progress = tmp_path / "progression.jsonl"
    progress.write_text('{"t": 0, "stage": "probe", "msg": "Lecture"}\n', encoding="utf-8")
    record = dict(id="j1", kind="analyze", title="film", args=[], command="pad-guard analyze film", progress_file=str(progress),
                  log_dir=str(directory), state="running", pid=999999, started=0.0)
    (directory / "j1.json").write_text(json.dumps(record), encoding="utf-8")
    job = jobs_mod.JobManager(directory).current()
    assert job.state == "interrupted"  # its process is gone without the end line
    snap = jobs_mod.snapshot(job)
    assert snap["stages"][0]["state"] == "failed" and "interrompu" in snap["journal"][-1]["msg"]
    progress.write_text(progress.read_text(encoding="utf-8") + '{"t": 9, "stage": "done", "msg": "CONFORME", '
                        '"status": "CONFORME", "indicative": false}\n', encoding="utf-8")
    record["id"] = "j2"
    (directory / "j2.json").write_text(json.dumps(record), encoding="utf-8")
    assert jobs_mod.JobManager(directory).current().state == "done"


def test_launch_refused_when_preflight_fails(lab, lab_client, analyses, tmp_path) -> None:
    film = tmp_path / "film.mov"
    film.write_bytes(b"0")
    profile = lab.root / "profiles" / "test_classic.yaml"
    profile.write_text(profile.read_text(encoding="utf-8").replace("silence_max_seconds:", "silence_max_seconds: null #"),
                       encoding="utf-8")
    body = {"master": str(film), "profile": "test_classic"}
    plan = lab_client.post("/api/jobs/analyze/preview", json=body).json()
    assert any("audio.silence_max_seconds" in x for x in plan["problems"])
    r = lab_client.post("/api/jobs/analyze", json=body)
    assert r.status_code == 400 and "profil incomplet" in r.json()["error"]
    assert not any(analyses.glob("film_*"))


# --- analyses already made and the report screen ------------------------------------------------

from typer.testing import CliRunner  # noqa: E402

from pad_guard.cli import app as cli_app  # noqa: E402


def _analyse(root: Path, film: Path, profile: Path, name: str) -> Path:
    out = root / name
    result = CliRunner().invoke(cli_app, ["analyze", str(film), "--profile", str(profile), "--out", str(out)])
    assert result.exit_code in (0, 4), result.output
    return out


@pytest.mark.fixtures
def test_report_screen_reads_rapport_json(lab, lab_client, analyses, fixtures_dir, tmp_path) -> None:
    work = _analyse(analyses, fixtures_dir / "bad_levels.mov", lab.root / "profiles" / "test_classic.yaml",
                    "bad_levels_20261024-1000")
    draft = lab.root / "profiles" / "brouillon.yaml"
    draft.write_text((lab.root / "profiles" / "test_classic.yaml").read_text(encoding="utf-8")
                     .replace("name: test_classic", "name: brouillon").replace("status: validated", "status: draft"),
                     encoding="utf-8")
    _analyse(analyses, fixtures_dir / "ok_prores.mov", draft, "ok_prores_20261024-1100")
    runs = {r["id"]: r for r in lab_client.get("/api/runs").json()["runs"]}
    assert runs["bad_levels_20261024-1000"]["label"] == "NON-CONFORME" and runs["bad_levels_20261024-1000"]["tone"] == "nc"
    indicative = runs["ok_prores_20261024-1100"]
    assert indicative["tone"] == "draft" and "CONFORME" not in indicative["label"].replace("NON-CONFORME", "")
    assert indicative["label"].startswith("INDICATIF")  # a draft profile never shows CONFORME

    data = lab_client.get("/api/runs/bad_levels_20261024-1000/report").json()
    view = json.loads((work / wd.REPORT_JSON).read_text(encoding="utf-8"))
    assert data["report"] == view and data["tone"] == "nc" and data["run"]["duration"]
    shown = [e for e in view["events"] if e["thumbnail"]]
    key = shown[0]["key"]
    img = lab_client.get(f"/api/runs/bad_levels_20261024-1000/thumb/{key}")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    assert lab_client.get("/api/runs/bad_levels_20261024-1000/thumb/video_y_high@0@").status_code == 404
    pdf = lab_client.get("/api/runs/bad_levels_20261024-1000/file/rapport.pdf?download=1")
    assert pdf.status_code == 200 and "attachment" in pdf.headers["content-disposition"]
    assert lab_client.get("/api/runs/bad_levels_20261024-1000/file/probe.json").status_code == 404
    assert lab_client.get("/api/runs/..%5C..%5Cx/report").status_code == 404
    opened = []
    lab.extra["opener"] = opened.append
    assert lab_client.post("/api/runs/bad_levels_20261024-1000/open-folder").status_code == 200 and opened == [work]

    # The id of an anomaly is a rank: the key stays, even when the events are renumbered.
    view["duplicate_keys"] = [key]
    (work / wd.REPORT_JSON).write_text(json.dumps(view), encoding="utf-8")
    assert lab_client.get(f"/api/runs/bad_levels_20261024-1000/thumb/{key}").status_code == 409


@pytest.mark.fixtures
def test_rerun_from_the_report(lab, lab_client, analyses, fixtures_dir) -> None:
    work = _analyse(analyses, fixtures_dir / "bad_levels.mov", lab.root / "profiles" / "test_classic.yaml", "relance")
    before = (work / wd.EVENTS).read_bytes()
    snap = lab_client.post("/api/runs/relance/rerun", json={"from": "rules"}).json()
    assert snap["kind"] == "rerun" and snap["command"].startswith("pad-guard rerun ")
    job = lab.extra["jobs"].wait()
    assert job.state == "done", jobs_mod.error_lines(job)
    assert (work / wd.EVENTS).read_bytes() == before  # same JSON, same rules
    run = json.loads((work / wd.RUN).read_text(encoding="utf-8"))
    assert run["reruns"][-1]["from_step"] == "rules"
    assert lab_client.post("/api/runs/relance/rerun", json={"from": "probe"}).status_code == 400


# --- Profils: draft from a PDF and its review ---------------------------------------------------

import yaml  # noqa: E402

from test_draft import LOUD_QUOTE, R128_QUOTE, TP_QUOTE, FakeClient, finding  # noqa: E402

from pad_guard.draft import make_draft  # noqa: E402
from pad_guard.profiles import resolve_profile  # noqa: E402


@pytest.fixture
def draft_lab(lab, tmp_path):
    """profiles/chaine_test.yaml (base, extends the norms) + profiles/drafts/chaine_test.yaml, PDF in diffuseurs/."""
    raw = yaml.safe_load((TEST_PROFILES / "test_classic.yaml").read_text(encoding="utf-8"))
    raw["meta"].update(name="chaine_test", extends=["ebu_r103", "ebu_r128", "lumiris_maison"])
    (lab.root / "profiles" / "chaine_test.yaml").write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False),
                                                            encoding="utf-8")
    (lab.root / "diffuseurs").mkdir()
    doc = pdf_fixture.make(lab.root / "diffuseurs" / "chaine_test.pdf")
    client = FakeClient({1: [
        finding("audio.true_peak_max_dbtp", -1, 1, TP_QUOTE),
        finding("audio.loudness.long.integrated_lufs", None, 1, R128_QUOTE, source_type="client_refers_to_norm",
                norm="EBU R128"),
        finding("audio.sample_rate", 48000, 2, "Audio | 48 kHz, 24 bits"),
        finding("audio.sample_rate", 48, 2, "Audio 48 kHz, 24 bits"),
    ]})
    make_draft(doc, "chaine_test", client, lab.root / "profiles" / "drafts", broadcaster="Chaîne de test")
    return lab


def test_review_needs_an_explicit_decision_per_field(draft_lab, lab_client) -> None:
    data = lab_client.get("/api/drafts/chaine_test/review").json()
    by = {q["path"]: q for q in data["questions"]}
    assert set(by) == {"audio.sample_rate", "audio.loudness.long.integrated_lufs", "audio.true_peak_max_dbtp"}
    conflict = by["audio.sample_rate"]
    assert conflict["status"] == "CONFLIT" and any(f["implausible"] for f in conflict["findings"])  # shown in red
    assert by["audio.loudness.long.integrated_lufs"]["reference"]["norm"] == "ebu_r128"
    assert [r["norm"] for r in data["references"]] == ["ebu_r128"] and data["pdf_available"]
    state = lab_client.get("/api/drafts/chaine_test/check").json()
    assert not state["ready"] and len(state["pending"]) == 3 and state["pending_references"] == ["ebu_r128"]
    refused = lab_client.post("/api/drafts/chaine_test/validate", json={"who": "Vincent"})
    assert refused.status_code == 400 and "incomplète" in refused.json()["error"]

    assert lab_client.put("/api/drafts/chaine_test/decision", json={"path": "audio.sample_rate", "answer": "a"}).status_code == 400
    good = next(c["n"] for c in conflict["candidates"] if c["value"] == "48000")
    lab_client.put("/api/drafts/chaine_test/decision", json={"path": "audio.sample_rate", "answer": str(good)})
    bad = lab_client.put("/api/drafts/chaine_test/decision", json={"path": "audio.true_peak_max_dbtp", "answer": "c", "value": "fort"})
    assert bad.status_code == 400
    fixed = lab_client.put("/api/drafts/chaine_test/decision", json={"path": "audio.true_peak_max_dbtp", "answer": "c",
                                                                     "value": "-3", "page": "1", "quote": "le niveau des crêtes"}).json()
    assert fixed["answer"] == "c" and "corrigé à la relecture" in fixed["decision"]["source"]
    lab_client.put("/api/drafts/chaine_test/decision", json={"path": "audio.loudness.long.integrated_lufs", "answer": "v"})
    # Reference refused: audio_loudness (blocking) would rest on EBU R 128 only, capped at minor.
    lab_client.post("/api/drafts/chaine_test/reference", json={"norm": "ebu_r128", "confirmed": False})
    state = lab_client.get("/api/drafts/chaine_test/check").json()
    assert state["ready"] and any("rules.severity.audio_loudness (blocking)" in r for r in state["risks"])
    r = lab_client.post("/api/drafts/chaine_test/validate", json={"who": "Vincent"})
    assert r.status_code == 400 and "confirmation" in r.json()["error"]
    # Decisions survive a restart of the server (saved next to the draft).
    lab_client.get("/api/drafts/chaine_test/review?fresh=1")
    lab_client.post("/api/drafts/chaine_test/reference", json={"norm": "ebu_r128", "confirmed": True})
    state = lab_client.get("/api/drafts/chaine_test/check").json()
    assert state["ready"] and not state["risks"]
    exists = lab_client.post("/api/drafts/chaine_test/validate", json={"who": "Vincent"})
    assert exists.status_code == 409  # profiles/chaine_test.yaml is there: replacing it is asked for
    done = lab_client.post("/api/drafts/chaine_test/validate", json={"who": "Vincent", "overwrite": True}).json()
    assert done["validated_by"] == "Vincent" and done["file"] == "profiles/chaine_test.yaml"
    prof = resolve_profile(draft_lab.root / "profiles" / "chaine_test.yaml")
    assert prof.profile.meta.status == "validated" and prof.profile.audio.true_peak_max_dbtp == -3.0
    assert prof.profile.audio.sample_rate == 48000 and [x.norm for x in prof.profile.meta.refers_to] == ["ebu_r128"]
    drafts = lab_client.get("/api/profiles").json()["drafts"]
    assert next(d for d in drafts if d["name"] == "chaine_test")["validated"]  # badge cleared


def test_draft_job_copies_the_pdf_and_runs_the_cli(lab, lab_client, tmp_path, monkeypatch) -> None:
    started = []
    monkeypatch.setattr(lab.extra["jobs"], "start", lambda kind, title, args, progress, *a, **k: started.append(args)
                        or jobs_mod.Job(id="x", kind=kind, title=title, args=args, command="", progress_file=str(progress),
                                        log_dir=str(tmp_path)))
    doc = pdf_fixture.make(tmp_path / "Cahier FTV.pdf")
    assert lab_client.post("/api/jobs/draft", json={"pdf": str(doc), "name": "Pas Bon"}).status_code == 400
    lab_client.post("/api/jobs/draft", json={"pdf": str(doc), "name": "ftv_hd", "broadcaster": "France Télévisions"})
    copy = lab.root / "diffuseurs" / "Cahier FTV.pdf"
    assert copy.read_bytes() == doc.read_bytes()
    assert started[-1] == ["draft-profile", str(copy), "--name", "ftv_hd", "--out-dir", str(lab.root / "profiles" / "drafts"),
                           "--broadcaster", "France Télévisions"]
    other = tmp_path / "autre" / "Cahier FTV.pdf"
    other.parent.mkdir()
    pdf_fixture.make(other)
    other.write_bytes(other.read_bytes() + b"%")
    clash = lab_client.post("/api/jobs/draft", json={"pdf": str(other), "name": "ftv_hd"})
    assert clash.status_code == 400 and "porte déjà ce nom" in clash.json()["error"]


def test_page_preview_of_the_draft(draft_lab, lab_client) -> None:
    r = lab_client.get("/api/drafts/chaine_test/page/1")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png" and r.content[:4] == b"\x89PNG"


def test_quote_highlighted_on_its_page(draft_lab, lab_client) -> None:
    from pad_guard.draft.pdf import quote_boxes

    doc = draft_lab.root / "diffuseurs" / "chaine_test.pdf"
    one = quote_boxes(doc, 1, TP_QUOTE)
    assert len(one) == 1 and all(0 <= v <= 1 for v in one[0]) and one[0][0] < one[0][2]
    assert len(quote_boxes(doc, 1, LOUD_QUOTE + " avec une tolérance de ± 1 LU.")) == 2  # two printed lines
    assert quote_boxes(doc, 2, "Audio | 48 kHz, 24 bits")  # table row quoted cell by cell
    assert quote_boxes(doc, 1, "phrase absente du document") == [] and quote_boxes(doc, 9, TP_QUOTE) == []
    r = lab_client.get("/api/drafts/chaine_test/highlight", params={"page": 1, "quote": TP_QUOTE}).json()
    assert r["found"] and set(r["boxes"][0]) == {"x0", "top", "x1", "bottom"}
