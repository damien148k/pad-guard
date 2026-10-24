from __future__ import annotations

import pytest

from pad_guard import audio_map
from pad_guard.audio_map import AudioMapError
from pad_guard.rules.profile import load_profile

from conftest import PROFILES

ARTE = load_profile(PROFILES / "arte_hd_sdr.yaml")


def groups(spec: str) -> list[tuple[str, list[int], str, bool]]:
    return [(g.name, g.tracks, g.layout, g.required) for g in audio_map.parse(spec, ARTE).groups]


def test_profile_default() -> None:
    m = audio_map.from_profile(ARTE)
    assert (m.source, m.spec) == ("profile", None)
    assert [(g.name, g.required) for g in m.groups] == [("VO", True), ("VF", False), ("VI", False)]


def test_parse_ranges_and_layouts() -> None:
    assert groups("VO:1-2,VF:3-4") == [("VO", [1, 2], "stereo", True), ("VF", [3, 4], "stereo", True)]
    assert groups(" VO : 1+3 : dual_mono , 5.1:5-10") == [
        ("VO", [1, 3], "dual_mono", True),
        ("5.1", [5, 6, 7, 8, 9, 10], "5.1", True),
    ]
    assert groups("Commentaire:7") == [("Commentaire", [7], "mono", True)]
    m = audio_map.parse("VO:1-2,VF:3-4", ARTE)
    assert (m.source, m.spec) == ("command_line", "VO:1-2,VF:3-4")
    assert audio_map.describe(m.groups) == "VO 1-2, VF 3-4"


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ("VO:1-2,VF:2-3", "plusieurs groupes"),
        ("VO:1-2,VO:3-4", "en double"),
        ("VO:1-3", "aucun layout"),
        ("VO:1-2:5.1", "attend 6"),
        ("VO:1:quad", "inconnu"),
        ("VO:a-b", "illisibles"),
        ("VO:2-1", "à l'envers"),
        ("VO:0-1", "à partir de 1"),
        ("VO", "NOM:PISTES"),
        (":1-2", "NOM:PISTES"),
        ("VO:1-2,", "groupe vide"),
    ],
)
def test_parse_errors(spec: str, message: str) -> None:
    with pytest.raises(AudioMapError, match=message):
        audio_map.parse(spec, ARTE)
