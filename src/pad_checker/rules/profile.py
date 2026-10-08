"""Broadcaster profile (YAML) schema and loader.

Every threshold used by the tool lives in a profile. Unknown fields are rejected so that a
typo cannot silently disable a rule. Fields that a broadcaster document leaves open are
``null`` in the YAML; :func:`null_fields` lists them so that the rules engine can refuse to
run a rule that depends on one (SPEC §9, CLAUDE.md principle 2).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from pad_checker import timecode
from pad_checker.rules import expr

Severity = Literal["blocking", "major", "minor", "info"]

# Anomaly types known to the rules engine (SPEC §5-§7). A severity table or a
# min_event_frames entry for any other name is a typo.
EVENT_TYPES = (
    "white_clip",
    "black_crush",
    "gamut",
    "freeze",
    "isolated_black_frame",
    "duplicate_frame",
    "pse",
    "letterbox",
    "audio_loudness",
    "audio_true_peak",
    "audio_short_term_excursion",
    "audio_lra",
    "audio_silent_track",
    "audio_dual_mono_mismatch",
    "audio_silence",
    "audio_phase",
    "audio_clipping",
    "structure_bars",
    "structure_black",
    "structure_timecode",
    "structure_bars_present",
    "structure_black_too_long",
    "format",
    "integrity",
)
EventType = Literal[EVENT_TYPES]  # type: ignore[valid-type]

# Event fields usable in severity expressions (SPEC §7.1).
EVENT_FIELDS = ("duration_frames", "worst_value", "area_pct_max", "threshold", "frame_start", "frame_end")
SCORE_FIELDS = ("blocking", "major", "minor", "info")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def _check_tc(value: str | None) -> str | None:
    if value is not None and not timecode.is_valid(value, fps=60):
        raise ValueError(f"timecode invalide {value!r}, format attendu HH:MM:SS:FF")
    return value


# --- profile ------------------------------------------------------------------------------


class ProfileMeta(_Model):
    name: str
    version: str
    broadcaster: str
    source_document: str
    notes: str | None = None


# --- format -------------------------------------------------------------------------------


class CodecSpec(_Model):
    codec_name: str
    profile: str


class LetterboxFormat(_Model):
    aspect: str
    active_lines: int
    first_line: int
    last_line: int
    active_pixels: int


class Letterbox(_Model):
    check: bool
    formats: list[LetterboxFormat]
    tolerance_lines: int | None


class Format(_Model):
    codecs: list[CodecSpec] = Field(min_length=1)
    containers: list[Literal["mov", "mxf"]] = Field(min_length=1)
    pix_fmt: str
    width: int
    height: int
    fps_allowed: list[str] = Field(min_length=1)
    field_order: Literal["progressive", "tt", "bb", "tb", "bt"]
    color_primaries: str
    color_transfer: str
    color_space: str
    color_range: Literal["tv", "pc"]
    unknown_color_tags_severity: Severity
    letterbox: Letterbox | None = None

    @field_validator("fps_allowed")
    @classmethod
    def _rational(cls, v: list[str]) -> list[str]:
        for fps in v:
            num, _, den = fps.partition("/")
            if not (num.isdigit() and den.isdigit() and int(den) > 0):
                raise ValueError(f"cadence {fps!r} : format attendu 'num/den', ex. '25/1'")
        return v


# --- video --------------------------------------------------------------------------------


class Video(_Model):
    bit_depth: Literal[10]
    y_min_legal: int
    y_max_legal: int
    y_tolerance_low_pct: float
    y_tolerance_high_pct: float
    rgb_min_pct: float
    rgb_max_pct: float
    max_out_of_range_area_pct: float
    prefilter: bool
    # Horizontal binomial low-pass applied before measuring: 3 = [1 2 1]/4, 5 = [1 4 6 4 1]/16.
    prefilter_taps: Literal[3, 5] | None = None
    measure_spaces: list[Literal["ycbcr", "rgb"]] | None = None

    @model_validator(mode="after")
    def _prefilter(self) -> Video:
        if self.prefilter and self.prefilter_taps is None:
            raise ValueError("prefilter est vrai : prefilter_taps est obligatoire (3 ou 5)")
        return self


# --- audio --------------------------------------------------------------------------------


class AudioGroup(_Model):
    name: str
    tracks: list[int] = Field(min_length=1)
    layout: Literal["mono", "dual_mono", "stereo", "5.1"]
    required: bool

    @model_validator(mode="after")
    def _channels(self) -> AudioGroup:
        expected = {"mono": 1, "dual_mono": 2, "stereo": 2, "5.1": 6}[self.layout]
        if len(self.tracks) != expected:
            raise ValueError(f"groupe {self.name!r} : layout {self.layout} attend {expected} piste(s)")
        if any(t < 1 for t in self.tracks):
            raise ValueError(f"groupe {self.name!r} : les pistes sont numérotées à partir de 1")
        return self


def check_groups(groups: list[AudioGroup], where: str) -> None:
    """Raise ValueError if two groups share a name or a track."""
    names = [g.name for g in groups]
    if len(set(names)) != len(names):
        raise ValueError(f"{where} : noms de groupe en double")
    used = [t for g in groups for t in g.tracks]
    if len(set(used)) != len(used):
        raise ValueError(f"{where} : une même piste appartient à plusieurs groupes")


class LoudnessRules(_Model):
    integrated_lufs: float
    integrated_tolerance_lu: float
    lra_max_lu: float | None = None
    lra_recommended_range_lu: tuple[float, float] | None = None  # information only
    short_term_dialogue_excursion_lu: float | None = None
    short_term_max_lufs: float | None = None
    short_term_excursion_above_lu: float | None = None


class Loudness(_Model):
    # Programs strictly shorter than this use ``short``. Without ``short``, ``long`` applies to all.
    long_program_min_seconds: float | None = None
    long: LoudnessRules
    short: LoudnessRules | None = None

    @model_validator(mode="after")
    def _short_needs_threshold(self) -> Loudness:
        if self.short is not None and self.long_program_min_seconds is None:
            raise ValueError("loudness.short est défini : loudness.long_program_min_seconds est obligatoire")
        return self


class Tone(_Model):
    hz: float
    dbfs: float


class AvSync(_Model):
    audio_early_max: float
    audio_late_max: float


class Audio(_Model):
    sample_rate: int
    bit_depth: int
    bit_depth_allowed: list[int] | None = None
    same_bit_depth_all_tracks: bool | None = None
    channel_layout: Literal["stereo_pairs"] | None = None
    max_pairs: int | None = None
    no_silent_tracks: bool | None = None
    silent_track_dbfs: float | None = None
    dual_mono_must_be_identical: bool | None = None
    groups: list[AudioGroup] = Field(min_length=1)
    loudness_exempt_groups: list[str] | None = None
    loudness: Loudness
    true_peak_max_dbtp: float
    alignment_tone: Tone | None = None
    silence_dbfs: float
    silence_max_seconds: float | None
    phase_min_correlation: float
    phase_min_seconds: float | None
    av_sync_ms: AvSync | None = None  # information only, not measurable without a reference
    exclude_head_tail: bool

    @model_validator(mode="after")
    def _groups(self) -> Audio:
        check_groups(self.groups, "audio.groups")
        names = [g.name for g in self.groups]
        for name in self.loudness_exempt_groups or []:
            if name not in names:
                raise ValueError(f"audio.loudness_exempt_groups : groupe inconnu {name!r}")
        return self


# --- structure ----------------------------------------------------------------------------


class TimecodeRules(_Model):
    file_start: str
    program_start: str
    tolerance_frames: int
    drop_frame_allowed: bool
    must_be_continuous: bool | None = None

    _tc = field_validator("file_start", "program_start")(_check_tc)


class Bars(_Model):
    required: bool
    forbidden: bool | None = None
    start_tc: str | None = None
    min_seconds: float | None = None
    pattern: Literal["ebu_75", "ebu_100", "smpte_hd"] | None = None
    tone_hz: float | None = None
    tone_dbfs: float | None = None
    tone_tolerance_db: float | None = None  # level of the tone, sine-referenced RMS
    tolerance: float | None = None  # mean error per bar region, 10-bit code values

    _tc = field_validator("start_tc")(_check_tc)

    @model_validator(mode="after")
    def _consistent(self) -> Bars:
        if self.required and self.forbidden:
            raise ValueError("structure.bars : required et forbidden ne peuvent pas être vrais ensemble")
        return self


class Black(_Model):
    head_min_seconds: float | None = None
    tail_min_seconds: float | None = None
    head_max_seconds: float | None = None
    tail_max_seconds: float | None = None
    y_max: int
    silence_dbfs: float


class FirstFrames(_Model):
    no_subtitles_first_frames: int


class Logo(_Model):
    forbidden: bool


class Credits(_Model):
    end_credits_max_seconds: dict[str, float]
    silent_black_credits_forbidden: bool


class Freeze(_Model):
    threshold: float
    min_seconds: float


class Pse(_Model):
    enabled: bool
    max_flashes_per_second: int
    flash_min_delta_pct: float
    flash_min_area_pct: float


class TitleSafe(_Model):
    horizontal: float
    vertical: float


class SafeAreas(_Model):
    title_safe_pct: TitleSafe
    subtitle_safe: str
    logo_corners_free: bool


class Structure(_Model):
    leaders: Literal["classic", "none"]
    timecode: TimecodeRules
    bars: Bars
    black: Black
    freeze: Freeze
    pse: Pse
    first_frames: FirstFrames | None = None  # information only
    logo: Logo | None = None  # information only
    credits: Credits | None = None  # information only
    safe_areas: SafeAreas | None = None  # information only


# --- rules --------------------------------------------------------------------------------


DEDUCED = "DEDUIT"
DEDUCED_MAX: tuple[Severity, ...] = ("minor", "info")


def is_deduced(source: str) -> bool:
    return source.strip().upper().startswith(DEDUCED)


class SeverityRule(_Model):
    if_: str | None = Field(default=None, alias="if")
    then: Severity | None = None
    else_: Severity | None = Field(default=None, alias="else")
    # Where the severity comes from: a paragraph of the broadcaster document ("Arte §3.2.3.3"),
    # or "DEDUIT" when no document says it. A deduced rule cannot go beyond minor.
    source: str = Field(min_length=1)

    @property
    def severity(self) -> Severity:
        return self.else_ if self.else_ is not None else self.then

    @model_validator(mode="after")
    def _shape(self) -> SeverityRule:
        if (self.else_ or self.then) and is_deduced(self.source) and self.severity not in DEDUCED_MAX:
            raise ValueError(
                f"règle de source {self.source!r} : une règle DEDUIT ne peut pas dépasser minor "
                f"(gravité {self.severity})"
            )
        if self.else_ is not None:
            if self.if_ is not None or self.then is not None:
                raise ValueError("une règle 'else' ne peut pas avoir de 'if' ni de 'then'")
        elif self.if_ is None or self.then is None:
            raise ValueError("une règle doit être {if: ..., then: ...} ou {else: ...}")
        else:
            try:
                expr.parse(self.if_, EVENT_FIELDS)
            except expr.ExpressionError as exc:
                raise ValueError(str(exc)) from exc
        return self


class Rules(_Model):
    merge_gap_frames: int = Field(ge=0)
    min_event_frames: dict[EventType, int]  # type: ignore[valid-type]
    max_major: int = Field(ge=0)
    score_formula: str
    severity: dict[EventType, list[SeverityRule]]  # type: ignore[valid-type]

    @field_validator("score_formula")
    @classmethod
    def _formula(cls, v: str) -> str:
        try:
            expr.parse(v, SCORE_FIELDS)
        except expr.ExpressionError as exc:
            raise ValueError(str(exc)) from exc
        return v

    @field_validator("severity")
    @classmethod
    def _ends_with_else(cls, v: dict[str, list[SeverityRule]]) -> dict[str, list[SeverityRule]]:
        for name, chain in v.items():
            if not chain or chain[-1].else_ is None:
                raise ValueError(f"severity.{name} : la dernière règle doit être {{else: ...}}")
            if any(r.else_ is not None for r in chain[:-1]):
                raise ValueError(f"severity.{name} : 'else' ne peut être que la dernière règle")
        return v


# --- llm ----------------------------------------------------------------------------------


class Llm(_Model):
    backend: Literal["ollama"]
    model: str
    fallback_model: str
    num_ctx: int
    temperature: float
    language: str


# --- root ---------------------------------------------------------------------------------


class Profile(_Model):
    profile: ProfileMeta
    format: Format
    video: Video
    audio: Audio
    structure: Structure
    rules: Rules
    llm: Llm


class ProfileError(Exception):
    """Profile could not be loaded. ``messages`` are user-facing, in French."""

    def __init__(self, path: Path, messages: list[str]):
        self.path = path
        self.messages = messages
        super().__init__(f"{path}: " + "; ".join(messages))


def _loc(loc: tuple[Any, ...]) -> str:
    parts: list[str] = []
    for item in loc:
        if isinstance(item, int):
            parts.append(f"[{item}]")
        else:
            parts.append(("." if parts else "") + str(item))
    return "".join(parts)


def _translate(err: dict[str, Any]) -> str:
    where = _loc(err["loc"]) or "(racine)"
    kind = err["type"]
    if kind == "extra_forbidden":
        return f"champ inconnu « {where} » (faute de frappe ?)"
    if kind == "missing":
        return f"champ obligatoire manquant « {where} »"
    if kind == "literal_error":
        return f"« {where} » : valeur {err.get('input')!r} non autorisée ({err['msg']})"
    msg = err["msg"].removeprefix("Value error, ")
    return f"« {where} » : {msg}"


def load_profile(path: str | Path) -> Profile:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ProfileError(path, ["fichier introuvable"]) from None
    except yaml.YAMLError as exc:
        raise ProfileError(path, [f"YAML invalide : {exc}"]) from None
    if not isinstance(raw, dict):
        raise ProfileError(path, ["le profil doit être un dictionnaire YAML"])
    try:
        return Profile.model_validate(raw)
    except ValidationError as exc:
        raise ProfileError(path, [_translate(e) for e in exc.errors()]) from None


class ProfileValueError(ValueError):
    """A rule needs a profile value that is absent or null. The message is user-facing (French)."""


def require(profile: Profile, dotted: str, purpose: str) -> Any:
    """Value at ``dotted`` (YAML names, e.g. ``structure.bars.tolerance``), or ProfileValueError.

    A value left at null in the YAML, or absent, never disables a rule silently (CLAUDE.md).
    """
    node: Any = profile
    parts = dotted.split(".")
    for i, part in enumerate(parts):
        if node is None:
            raise ProfileValueError(
                f"le profil ne renseigne pas « {'.'.join(parts[:i])} », nécessaire pour {purpose}"
            )
        name = next((n for n, f in type(node).model_fields.items() if (f.alias or n) == part), part)
        value = getattr(node, name)
        if value is None:
            where = ".".join(parts[: i + 1])
            if name in node.model_fields_set:
                raise ProfileValueError(
                    f"« {where} » vaut null dans le profil : {purpose} ne peut pas être contrôlé "
                    "tant que la valeur n'est pas renseignée"
                )
            raise ProfileValueError(f"le profil ne renseigne pas « {where} », nécessaire pour {purpose}")
        node = value
    return node


def null_fields(profile: Profile) -> list[str]:
    """Dotted paths of fields explicitly set to null in the YAML (values left open)."""
    out: list[str] = []

    def walk(model: BaseModel, prefix: str) -> None:
        for name in model.model_fields_set:
            value = getattr(model, name)
            field = type(model).model_fields[name]
            key = f"{prefix}{field.alias or name}"
            if value is None:
                out.append(key)
            elif isinstance(value, BaseModel):
                walk(value, key + ".")

    walk(profile, "")
    return sorted(out)
