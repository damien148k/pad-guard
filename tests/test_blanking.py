"""Blanking at the exact line (decision of Vincent, 31/10/2026): the edges of the active picture against the
expected format, two levels. Beyond the tolerance of the client (format.letterbox.tolerance_lines): the
anomaly « Format d'image » of the profile; within it but not exact: the house anomaly blanking_inexact,
minor, tolerance 0 in lumiris_maison.yaml."""

from __future__ import annotations

import json

import pytest
import yaml
from typer.testing import CliRunner

from pad_guard import workdir as wd
from pad_guard.cli import app
from pad_guard.profiles import resolve_profile

from conftest import ROOT, TEST_PROFILES

CLASSIC = TEST_PROFILES / "test_classic.yaml"  # extends lumiris_maison
ARTE = ROOT / "profiles" / "arte_hd_sdr.yaml"


def _profile(tmp_path):
    """test_classic with the format table of Arte §3.2.4 and its tolerance (2 lines, DEDUIT)."""
    arte = yaml.safe_load(ARTE.read_text(encoding="utf-8"))
    raw = yaml.safe_load(CLASSIC.read_text(encoding="utf-8"))
    raw["format"]["letterbox"] = arte["format"]["letterbox"]
    raw["rules"]["severity"]["letterbox"] = [{"else": "major", "source": "profil de test"}]
    path = tmp_path / "blanking.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _analyse(fixtures_dir, tmp_path, name):
    out = tmp_path / name
    result = CliRunner().invoke(app, ["analyze", str(fixtures_dir / f"{name}.mov"), "--profile",
                                      str(_profile(tmp_path)), "--out", str(out), "--no-thumbnails"])
    assert result.exception is None or isinstance(result.exception, SystemExit), result.output
    st = json.loads((out / wd.STRUCTURE).read_text(encoding="utf-8"))
    events = json.loads((out / wd.EVENTS).read_text(encoding="utf-8"))["events"]
    checks = {c["id"]: c for c in st["checks"]}
    mine = [e for e in events if e["type"] in ("letterbox", "blanking_inexact")]
    return st["letterbox"], checks, mine


@pytest.mark.fixtures
def test_blanking_exact(fixtures_dir, tmp_path) -> None:
    lb, checks, events = _analyse(fixtures_dir, tmp_path, "blank_exact")
    # ProRes HQ rings into rows 16-21 of the band: the edge stays on row 22.
    assert (lb["dominant"]["top"], lb["dominant"]["bottom"]) == (22, 1057)
    assert (lb["matched_format"], lb["deviation"], lb["expected"]) == ("1.85", 0, [22, 1057, 0, 1919])
    assert checks["letterbox"]["status"] == checks["blanking"]["status"] == "ok"
    assert "à la ligne exacte" in checks["blanking"]["actual"]
    assert events == []


@pytest.mark.fixtures
def test_blanking_one_line_off_is_a_house_anomaly(fixtures_dir, tmp_path) -> None:
    lb, checks, events = _analyse(fixtures_dir, tmp_path, "blank_1")
    assert (lb["dominant"]["top"], lb["dominant"]["bottom"], lb["deviation"]) == (23, 1058, 1)
    assert checks["letterbox"]["status"] == "ok" and checks["blanking"]["status"] == "fail"
    (e,) = events
    assert (e["type"], e["severity"], e["title"]) == ("blanking_inexact", "minor", "Blanking à la ligne exacte (règle maison)")
    assert "décision Vincent, 31/10/2026" in e["severity_source"]
    assert e["value_text"] == "lignes 23 à 1058, colonnes 0 à 1919 : écart de 1 ligne"
    assert e["threshold_text"] == "format 1.85 : lignes 22 à 1057, colonnes 0 à 1919, écart ≤ 0 ligne"


@pytest.mark.fixtures
def test_blanking_three_lines_off_is_the_client_anomaly(fixtures_dir, tmp_path) -> None:
    lb, checks, events = _analyse(fixtures_dir, tmp_path, "blank_3")
    assert (lb["dominant"]["top"], lb["dominant"]["bottom"], lb["deviation"]) == (25, 1060, 3)
    assert lb["matched_format"] is None and lb["nearest_format"] == "1.85"
    assert checks["letterbox"]["status"] == "fail" and "blanking" not in checks  # one anomaly, the client's
    (e,) = events
    assert (e["type"], e["severity"]) == ("letterbox", "major")  # the severity of the profile
    assert "le plus proche, 1.85, attend lignes 22 à 1057, colonnes 0 à 1919 (écart de 3 lignes)" in e["value_text"]


def test_house_value_and_arte_profile() -> None:
    eff = resolve_profile(ARTE, ROOT / "normes")
    assert eff.profile.video.blanking_tolerance_lines == 0
    assert eff.profile.format.letterbox.tolerance_lines == 2  # the client's tolerance is unchanged
    assert eff.profile.rules.chain("blanking_inexact")[0].severity == "minor"
    origin = eff.origins["video.blanking_tolerance_lines"]
    assert origin.file.endswith("lumiris_maison.yaml") and "décision Vincent, 31/10/2026" in origin.source
