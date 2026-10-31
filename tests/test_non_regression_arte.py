"""Non-regression reference of the real Arte master (31/10/2026): 57 events, NON-CONFORME.

The master is not in the repository: its reference is (tests/golden/arte_master/reference.json, written by
tools/recette/non_regression.py). With PAD_GUARD_ARTE_OUT=<out dir of the master>, the analysis is compared."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
from collections import Counter
from pathlib import Path

import pytest

from conftest import ROOT

_spec = importlib.util.spec_from_file_location("non_regression", ROOT / "tools" / "recette" / "non_regression.py")
nr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nr)

REFERENCE = json.loads(nr.REFERENCE.read_text(encoding="utf-8"))


def test_reference_is_57_events() -> None:
    assert REFERENCE["source"]["name"] == "176035_WebOfDeathThe_1080i_50_ProResHQ_feature.mov"
    assert REFERENCE["verdict"] == {"status": "NON-CONFORME", "score": 0.0}
    events = REFERENCE["events"]
    assert len(events) == 57
    assert Counter(e["severity"] for e in events) == {"minor": 39, "major": 16, "blocking": 2}
    assert Counter(e["type"] for e in events) == {
        "audio_silence": 20, "pse": 12, "duplicate_frame": 9, "audio_short_term_excursion": 6, "format_color_tags": 2,
        "audio_loudness": 1, "audio_lra": 1, "scan_flag_mismatch": 1, "structure_timecode": 1, "letterbox": 1,
        "freeze": 1, "gamut": 1, "white_clip": 1}
    # The 57th (31/10/2026, blanking at the exact line): a 2.39 picture of 808 lines, Arte's 2.35 has 816.
    (lb,) = [e for e in events if e["type"] == "letterbox"]
    assert (lb["severity"], lb["severity_source"]) == ("minor", "Arte §3.2.4")
    assert "808 lignes (lignes 136 à 943)" in lb["value_text"] and "(écart de 4 lignes)" in lb["value_text"]
    assert not any(e["type"] == "blanking_inexact" for e in events)


def test_compare_reports_every_difference() -> None:
    assert nr.compare(REFERENCE, REFERENCE) == []
    changed = copy.deepcopy(REFERENCE)
    gone = changed["events"].pop()
    changed["events"][0]["value_text"] += " (modifié)"
    diff = nr.compare(changed, REFERENCE)
    assert any(d.startswith("nouvel événement") and "(modifié)" in d for d in diff)
    assert sum(d.startswith("événement disparu") for d in diff) == 2 and gone["tc_start"] in diff[-2]
    assert diff[-1] == "56 événements au lieu de 57"


@pytest.mark.skipif(not os.environ.get("PAD_GUARD_ARTE_OUT"), reason="PAD_GUARD_ARTE_OUT : dossier d'analyse du master")
def test_master_against_reference() -> None:
    assert nr.compare(nr.summary(Path(os.environ["PAD_GUARD_ARTE_OUT"])), REFERENCE) == []
