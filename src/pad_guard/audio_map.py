"""Audio track mapping: profile default, or ``--audio-map`` override (e.g. ``"VO:1-2,VF:3-4"``).

The command-line map replaces ``audio.groups`` of the profile for one analysis. Syntax:
``NAME:TRACKS[:LAYOUT]`` separated by commas, where TRACKS is a track number, a range
(``1-2``, ``1-6``) or a ``+`` list (``1+3``). Without LAYOUT, the layout of the profile group
of the same name is kept if its track count matches, else it is deduced from the track count
(1 mono, 2 stereo, 6 5.1). Every group given on the command line is required: the operator
declares that it is in the file.
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, ValidationError

from pad_guard.rules.profile import AudioGroup, Profile, check_groups

Layout = Literal["mono", "dual_mono", "stereo", "5.1"]
_LAYOUT_BY_COUNT: dict[int, Layout] = {1: "mono", 2: "stereo", 6: "5.1"}


class AudioMapError(ValueError):
    """Invalid ``--audio-map``. The message is user-facing (French)."""


class AudioMap(BaseModel):
    source: Literal["profile", "command_line"]
    spec: str | None  # the --audio-map string as given, None when the profile map is used
    groups: list[AudioGroup]


def from_profile(profile: Profile) -> AudioMap:
    return AudioMap(source="profile", spec=None, groups=list(profile.audio.groups))


def _tracks(text: str, item: str) -> list[int]:
    out: list[int] = []
    for part in text.split("+"):
        first, sep, last = part.strip().partition("-")
        try:
            lo = int(first)
            hi = int(last) if sep else lo
        except ValueError:
            raise AudioMapError(f"« {item} » : pistes « {text} » illisibles (exemples : 1-2, 3, 1+3)") from None
        if hi < lo:
            raise AudioMapError(f"« {item} » : plage de pistes à l'envers « {part.strip()} »")
        out.extend(range(lo, hi + 1))
    return out


def parse(spec: str, profile: Profile) -> AudioMap:
    defaults = {g.name: g for g in profile.audio.groups}
    groups: list[AudioGroup] = []
    for item in (s.strip() for s in spec.split(",")):
        if not item:
            raise AudioMapError("--audio-map : groupe vide (virgule en trop ?)")
        fields = [f.strip() for f in item.split(":")]
        if len(fields) not in (2, 3) or not fields[0]:
            raise AudioMapError(f"« {item} » : format attendu NOM:PISTES ou NOM:PISTES:LAYOUT, ex. VO:1-2")
        name, tracks = fields[0], _tracks(fields[1], item)
        if len(fields) == 3:
            layout = fields[2]
            if layout not in get_args(Layout):
                raise AudioMapError(f"« {item} » : layout « {layout} » inconnu ({', '.join(get_args(Layout))})")
        elif name in defaults and len(defaults[name].tracks) == len(tracks):
            layout = defaults[name].layout
        elif len(tracks) in _LAYOUT_BY_COUNT:
            layout = _LAYOUT_BY_COUNT[len(tracks)]
        else:
            raise AudioMapError(
                f"« {item} » : {len(tracks)} pistes, aucun layout ne correspond "
                "(1 piste : mono ; 2 : stereo ou dual_mono ; 6 : 5.1)"
            )
        try:
            groups.append(AudioGroup(name=name, tracks=tracks, layout=layout, required=True))
        except ValidationError as exc:
            raise AudioMapError(f"« {item} » : {exc.errors()[0]['msg'].removeprefix('Value error, ')}") from None
    try:
        check_groups(groups, "mapping")
    except ValueError as exc:
        raise AudioMapError(str(exc)) from None
    return AudioMap(source="command_line", spec=spec, groups=groups)


def describe(groups: list[AudioGroup]) -> str:
    """Human-readable map, e.g. ``VO 1-2, VF 3-4``."""
    return ", ".join(f"{g.name} {tracks_text(g.tracks)}" for g in groups)


def tracks_text(tracks: list[int]) -> str:
    """``[1, 2]`` -> ``1-2``, ``[1, 3]`` -> ``1+3``."""
    if len(tracks) > 1 and tracks == list(range(tracks[0], tracks[-1] + 1)):
        return f"{tracks[0]}-{tracks[-1]}"
    return "+".join(map(str, tracks))
