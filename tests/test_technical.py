"""Profile « contrôle technique Lumiris » (Phase 6): everything measured, no verdict."""

from __future__ import annotations

import json
import re

import pytest
from typer.testing import CliRunner

from pad_guard import workdir as wd
from pad_guard.cli import app
from pad_guard.labels import status_label
from pad_guard.report import ai
from pad_guard.ui.runs import tone

from conftest import PROFILES

TECHNICAL = PROFILES / "lumiris_controle_technique.yaml"


def _analyse(path, out):
    result = CliRunner().invoke(app, ["analyze", str(path), "--profile", str(TECHNICAL), "--out", str(out),
                                      "--no-thumbnails"])
    assert result.exception is None or isinstance(result.exception, SystemExit), result.output
    return result


@pytest.mark.fixtures
def test_scan_gets_a_technical_report(fixtures_dir, tmp_path) -> None:
    """A 2K 8-bit 23.976 scan: no format anomaly (nothing is required), « Rapport technique »."""
    result = _analyse(fixtures_dir / "fmt_dnxhr_hq_2k.mov", tmp_path / "o")
    assert result.exit_code == 0
    verdict = json.loads((tmp_path / "o" / wd.VERDICT).read_text(encoding="utf-8"))
    assert verdict["technical"] is True
    events = json.loads((tmp_path / "o" / wd.EVENTS).read_text(encoding="utf-8"))["events"]
    assert not [e for e in events if e["type"].startswith("format")]
    md = (tmp_path / "o" / wd.REPORT_MD).read_text(encoding="utf-8")
    assert "**Rapport technique**" in md and not re.search(r"(?i)\bconforme\b", md.split("## 7.")[0])
    rows = [line for line in md.splitlines() if line.startswith(("| Codec et profil |", "| Résolution |", "| Cadence |"))]
    assert len(rows) == 3 and all("tout (contrôle technique)" in r and r.endswith("| OK |") for r in rows)
    report = json.loads((tmp_path / "o" / wd.REPORT_JSON).read_text(encoding="utf-8"))
    assert report["verdict"]["technical"] and report["verdict"]["label"] == "Rapport technique"
    assert "Rapport technique" in result.output


@pytest.mark.fixtures
def test_colour_tags_have_their_own_type(fixtures_dir, tmp_path) -> None:
    """DV without colour tags: the only format events are « format_color_tags » (info), against BT.709."""
    _analyse(fixtures_dir / "sd_dv.mov", tmp_path / "o")
    events = json.loads((tmp_path / "o" / wd.EVENTS).read_text(encoding="utf-8"))["events"]
    fmt = [e for e in events if e["type"].startswith("format")]
    assert {(e["type"], e["severity"], e["value_text"]) for e in fmt} == {("format_color_tags", "info", "non renseigné")}
    assert sorted(e["title"] for e in fmt) == [
        "Colorimétrie : matrice", "Colorimétrie : primaires", "Colorimétrie : transfert"]


@pytest.mark.fixtures
def test_house_rules_keep_their_severity(fixtures_dir, tmp_path) -> None:
    """Full-range content tagged narrow: a house rule (major), listed in the technical report too."""
    _analyse(fixtures_dir / "fmt_full_as_tv.mov", tmp_path / "o")
    events = json.loads((tmp_path / "o" / wd.EVENTS).read_text(encoding="utf-8"))["events"]
    assert [e["severity"] for e in events if e["type"] == "range_content_mismatch"] == ["major"]
    levels = [e for e in events if e["type"] in ("white_clip", "black_crush", "gamut")]
    assert levels and all(e["severity"] in ("minor", "info") for e in levels)  # R 103: recommendations


def test_labels_and_ai_checks() -> None:
    assert status_label("NON-CONFORME", False, True) == "Rapport technique"
    assert tone({"status": "NON-CONFORME", "technical": True}) == "tech"
    verdict = {"statut": "NON-CONFORME", "indicatif": False, "technique": True, "affiche": "Rapport technique"}
    assert ai.opening(verdict) == "Rapport technique, sans verdict de conformité."
    assert ai.verdict_problems("Rapport technique : deux anomalies mineures.", verdict) == []
    assert ai.verdict_problems("Le fichier est NON-CONFORME.", verdict)
