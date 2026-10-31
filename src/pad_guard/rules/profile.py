"""Broadcaster profile (YAML) schema and loader.

Every threshold used by the tool lives in the effective profile: the broadcaster profile merged
over the norms it extends (``meta.extends``, SPEC §12, resolved by :mod:`pad_guard.profiles`).
Unknown fields are rejected so that a typo cannot silently disable a rule. Fields that a
document leaves open are ``null`` in the YAML; :func:`null_fields` lists them so that the rules
engine can refuse to run a rule that depends on one (SPEC §9, CLAUDE.md principle 2).
"""

from __future__ import annotations

import datetime as dt
import math
import re
from fractions import Fraction
from pathlib import Path
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

from pad_guard import timecode
from pad_guard.rules import expr

Severity = Literal["blocking", "major", "minor", "info"]

# Explicit « anything is accepted » for the comparison values of a technical profile (no
# broadcaster): never implied by an absent value (CLAUDE.md, null in a profile).
ANY = "any"
COHERENT = "coherent"  # colour tags: those coherent with the file (formats.coherent_tags)
Any_ = Literal["any"]

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
    # One type per kind of format check; without its own chain, the chain of "format" applies.
    "format_container",
    "format_codec",
    "format_picture",
    "format_resolution",
    "format_frame_rate",
    "format_color_tags",
    "integrity",
    "alpha_channel",
    "audio_not_analysed",
    "range_content_mismatch",
    "range_tag_suspect",
    "delivery_conversion_required",
    "scan_flag_mismatch",
    "scan_interlaced",
)
EventType = Literal[EVENT_TYPES]  # type: ignore[valid-type]

# Event fields usable in severity expressions (SPEC §7.1). duration_s is the duration in seconds
# at the frame rate of the file: a duration written in frames would mean twice less time in 50p.
EVENT_FIELDS = ("duration_frames", "duration_s", "worst_value", "area_pct_max", "threshold", "frame_start",
                "frame_end")
SCORE_FIELDS = ("blocking", "major", "minor", "info")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


def _check_tc(value: str | None) -> str | None:
    if value is not None and value != ANY and not timecode.is_valid(value, 60):
        raise ValueError(f"timecode invalide {value!r}, format attendu HH:MM:SS:FF")
    return value


def _check_rates(v: list[str] | None) -> list[str] | None:
    if v == ANY:
        return v
    for fps in v or []:
        num, _, den = fps.partition("/")
        if not (num.isdigit() and den.isdigit() and int(den) > 0):
            raise ValueError(f"cadence {fps!r} : format attendu 'num/den', ex. '25/1'")
    return v


# --- profile ------------------------------------------------------------------------------


ProfileStatus = Literal["draft", "validated"]
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class NormReference(_Model):
    """An explicit reference of the client's document to a norm (« conforme à EBU R 128 »), confirmed
    by a human: the values that norm gives are the client's requirements, not capped (CLAUDE.md
    principle 2, decision of 24 October 2026). A value the client writes always wins."""

    norm: str = Field(description="Nom de la norme dans normes/ (doit figurer dans meta.extends)")
    source: str = Field(description="Citation du renvoi dans le document du client (paragraphe ou page, phrase)")
    # Fields of that norm the reference does not cover (« sauf le nombre de canaux audio »): they stay
    # recommendations, capped (decision of Damien, 25 October 2026).
    except_: list[str] = Field(default=[], alias="except",
                               description="Chemins des champs exclus du renvoi (ex. audio.groups)")
    # Version of the norm the document cites, when it is not the one of normes/ (« R 103 v2.0 »): the
    # version of normes/ applies, the report says so (decision of Damien, 25 October 2026).
    cited_version: str | None = Field(default=None, description="Version citée par le document, si elle diffère")

    @field_validator("source")
    @classmethod
    def _cited(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("renvoi sans citation du document")
        return v


class ProfileMeta(_Model):
    name: str
    version: str
    broadcaster: str
    source_document: str
    notes: str | None = None
    kind: Literal["profile"] = "profile"
    # Norms of normes/ (file names without extension) merged under this profile, in this order.
    extends: list[str] = []
    # Norms of extends the client's document explicitly refers to: their values are not capped.
    refers_to: list[NormReference] = []
    # draft: usable, but the report is only indicative and never says CONFORME (CLAUDE.md principle 7).
    status: ProfileStatus = "draft"
    validated_by: str | None = None
    validated_at: dt.date | None = None
    source_pdf: str | None = None  # broadcaster document, in diffuseurs/
    source_pdf_sha256: str | None = None
    # technical: a Lumiris check of a working file, no broadcaster: the report is a « Rapport
    # technique », never CONFORME or NON-CONFORME.
    purpose: Literal["delivery", "technical"] = "delivery"

    @field_validator("source_pdf_sha256")
    @classmethod
    def _sha(cls, v: str | None) -> str | None:
        if v is not None and not _SHA256.match(v):
            raise ValueError("empreinte SHA-256 attendue : 64 caractères hexadécimaux en minuscules")
        return v

    @model_validator(mode="after")
    def _validated(self) -> ProfileMeta:
        if self.status == "validated" and (self.validated_by is None or self.validated_at is None):
            raise ValueError("status: validated demande validated_by et validated_at")
        return self


class NormDocument(_Model):
    title: str
    version: str  # exact version of the document, e.g. "V5, novembre 2023"


class NormMeta(_Model):
    """``meta`` of a file of normes/: a partial profile whose every value cites its source."""

    kind: Literal["norm"]
    name: str
    document: NormDocument
    source_pdf: str | None = None  # in normes/sources/
    source_pdf_sha256: str | None = None
    notes: str | None = None
    extends: list[str] = []
    # Norms of extends this norm explicitly refers to (« conformément à EBU R 103 »): when a client
    # refers to this norm, their values are the client's requirements too (transitive reference).
    refers_to: list[NormReference] = []
    # always: proposed to every new draft profile; on_reference: only when the document cites it
    # (a national recommendation such as CST-RT-040).
    applies: Literal["always", "on_reference"] = "always"
    # A norm drafted from its PDF by the local AI is validated field by field by a human (review-profile).
    validated_by: str | None = None
    validated_at: dt.date | None = None
    # signer-norme: fingerprint of the review table Vincent read and signed (docs/normes/<name>.md).
    validated_table_sha256: str | None = None
    validated_norm_sha256: str | None = None  # the norm's content when signed (signature.norm_fingerprint)

    @field_validator("source_pdf_sha256", "validated_table_sha256", "validated_norm_sha256")
    @classmethod
    def _sha(cls, v: str | None) -> str | None:
        if v is not None and not _SHA256.match(v):
            raise ValueError("empreinte SHA-256 attendue : 64 caractères hexadécimaux en minuscules")
        return v

    @model_validator(mode="after")
    def _references_extended(self) -> NormMeta:
        missing = [r.norm for r in self.refers_to if r.norm not in self.extends]
        if missing:
            raise ValueError(f"refers_to : {', '.join(missing)} doit figurer dans extends")
        return self


# --- format -------------------------------------------------------------------------------


class CodecSpec(_Model):
    codec_name: str
    profile: str
    label: str | None = None  # name in the client's document ("XAVC HD Intra Class 100"), shown in the report


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


class Delivery(_Model):
    """Format the broadcaster expects in delivery; the master may differ (CLAUDE.md, Format de livraison)."""

    scan: Literal["progressive", "interlaced_tff", "interlaced_bff", "psf"] | None
    fps: list[str] | None = Field(min_length=1)
    codec: str | None  # information: the master is always transcoded by the facility

    _rates = field_validator("fps")(_check_rates)


class Format(_Model):
    # "any": a technical profile accepts every value (explicit, never implied).
    codecs: list[CodecSpec] | Any_ = Field(min_length=1)
    # mxf: any operational pattern; mxf_op1a / mxf_opatom: that pattern only.
    containers: list[Literal["mov", "mp4", "mxf", "mxf_op1a", "mxf_opatom"]] | Any_ = Field(min_length=1)
    # The decoded picture: bit depth and chroma sampling ("rgb" for an RGB file), or the older
    # form, one FFmpeg pixel format (pix_fmt). One of the two forms, not both.
    bit_depth_allowed: list[int] | Any_ | None = Field(default=None, min_length=1)
    chroma_allowed: list[Literal["4:2:0", "4:2:2", "4:4:4", "rgb"]] | Any_ | None = Field(default=None, min_length=1)
    pix_fmt: str | None = None
    width: int | Any_
    height: int | Any_
    fps_allowed: list[str] | Any_ = Field(min_length=1)
    # psf: progressive pictures carried as two fields (the flag may be interlaced or progressive).
    field_order: Literal["progressive", "psf", "tt", "bb", "tb", "bt", "any"]
    color_primaries: str
    color_transfer: str
    color_space: str
    color_range: Literal["tv", "pc", "any"]
    unknown_color_tags_severity: Severity
    letterbox: Letterbox | None = None
    delivery: Delivery | None = None

    _rates = field_validator("fps_allowed")(_check_rates)

    @model_validator(mode="after")
    def _picture(self) -> Format:
        sampled = self.bit_depth_allowed is not None or self.chroma_allowed is not None
        if self.pix_fmt is not None and sampled:
            raise ValueError("format : pix_fmt ou bit_depth_allowed + chroma_allowed, pas les deux")
        if self.pix_fmt is None and (self.bit_depth_allowed is None or self.chroma_allowed is None):
            raise ValueError("format : indiquer bit_depth_allowed et chroma_allowed (ou l'ancienne forme pix_fmt)")
        return self


# --- video --------------------------------------------------------------------------------


class ScanDetection(_Model):
    """Combing detection (SPEC §12.5): a moving frame is combed if its ``comb`` ratio reaches
    ``comb_ratio_min``; the share of combed frames among the moving ones gives the scan."""

    comb_ratio_min: float = Field(gt=0)
    motion_min: float = Field(ge=0)  # d_mean, 10-bit code values
    interlaced_min_pct: float = Field(ge=0, le=100)
    progressive_max_pct: float = Field(ge=0, le=100)
    min_moving_frames: int = Field(ge=1)

    @model_validator(mode="after")
    def _ordered(self) -> ScanDetection:
        if self.progressive_max_pct > self.interlaced_min_pct:
            raise ValueError("progressive_max_pct ne peut pas dépasser interlaced_min_pct")
        return self


class RangeDetection(_Model):
    """Coding range of the content against its tag (Phase 6): luma at the ends of the video data
    range, 4 and 1019 (ITU-R BT.709-6 item 4.7), in a file tagged narrow range."""

    reserved_min_frames_pct: float = Field(ge=0, le=100)


class Video(_Model):
    bit_depth: Literal[10]
    y_min_legal: int
    y_max_legal: int
    y_tolerance_low_pct: float
    y_tolerance_high_pct: float
    rgb_min_pct: float
    rgb_max_pct: float
    max_out_of_range_area_pct: float
    # above: error when the area is strictly above the threshold (EBU R 103 « exceeds 1% », CST-RT-040
    # « ne doit pas excéder ») ; at_least: from the threshold on (Arte « au moins 1 % »).
    out_of_range_area_error: Literal["above", "at_least"]
    prefilter: bool
    # Horizontal binomial low-pass applied before measuring: 3 = [1 2 1]/4, 5 = [1 4 6 4 1]/16.
    prefilter_taps: Literal[3, 5] | None = None
    measure_spaces: list[Literal["ycbcr", "rgb"]] | None = None
    scan_detection: ScanDetection | None = None
    range_detection: RangeDetection | None = None

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
    method: str | None = None  # information: measurement standard (EBU R 128 / ITU-R BS.1770)
    # Programs up to this duration use ``short``, longer ones ``long`` (CST-RT-040 p. 9: court <= 2 minutes,
    # long > 2 minutes; Arte: programmes > 2'00). Without ``short``, ``long`` applies to all.
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
    # unchecked: a technical profile; the file is the programme, head and tail are not checked.
    leaders: Literal["classic", "none", "unchecked"]
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
                expr.parse(self.if_, EVENT_FIELDS + PARAM_NAMES)
            except expr.ExpressionError as exc:
                raise ValueError(str(exc)) from exc
        return self


class RuleParams(_Model):
    """Named values used by the severity conditions (``rules.params.<name>`` in the profile, the
    bare name in a condition), so that a value and its source live in one place."""

    levels_major_min_seconds: float | None = Field(default=None, ge=0)


PARAM_NAMES = tuple(RuleParams.model_fields)


class Rules(_Model):
    # Ranges of anomalous frames closer than this are one event. In seconds (converted at the frame
    # rate of the file, rounded down); merge_gap_frames is the older form, in frames.
    merge_gap_seconds: float | None = Field(default=None, ge=0)
    merge_gap_frames: int | None = Field(default=None, ge=0)
    # Point audio events (true peak, short-term excursion, dual mono mismatch): exceedances closer
    # than this, in seconds, are one event, with the number of exceedances and the worst value.
    audio_merge_gap_seconds: float | None = Field(default=None, ge=0)
    # Minimum duration of an event, by type: in frames (1: a single frame counts) or in seconds
    # (converted at the frame rate of the file, rounded up).
    min_event_frames: dict[EventType, int] = Field(default_factory=dict)  # type: ignore[valid-type]
    min_event_seconds: dict[EventType, float] = Field(default_factory=dict)  # type: ignore[valid-type]
    params: RuleParams = Field(default_factory=RuleParams)
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

    @model_validator(mode="after")
    def _one_form(self) -> Rules:
        if (self.merge_gap_seconds is None) == (self.merge_gap_frames is None):
            raise ValueError("rules : indiquer merge_gap_seconds (ou l'ancienne forme merge_gap_frames), pas les deux")
        both = sorted(set(self.min_event_frames) & set(self.min_event_seconds))
        if both:
            raise ValueError(f"rules : durée minimale en images et en secondes pour {', '.join(both)}")
        return self

    def chain(self, event_type: str) -> list[SeverityRule] | None:
        """Severity chain of a type; the format checks without their own fall back on « format »."""
        if event_type in self.severity:
            return self.severity[event_type]
        if event_type.startswith("format_"):
            return self.severity.get("format")
        return None

    def gap_frames(self, fps: Fraction) -> int:
        """merge_gap in frames at ``fps`` (rounded down: 0.5 s is 12 frames at 25 frames/s)."""
        if self.merge_gap_seconds is None:
            return self.merge_gap_frames
        return math.floor(Fraction(str(self.merge_gap_seconds)) * fps)

    def audio_gap_frames(self, fps: Fraction) -> int:
        """audio_merge_gap_seconds in frames at ``fps`` (rounded down, like merge_gap)."""
        if self.audio_merge_gap_seconds is None:
            raise ProfileValueError("le profil ne renseigne pas « rules.audio_merge_gap_seconds », nécessaire pour "
                                    "le regroupement des événements audio ponctuels")
        return math.floor(Fraction(str(self.audio_merge_gap_seconds)) * fps)

    def min_frames(self, event_type: str, fps: Fraction) -> int:
        """Minimum duration of an event of this type, in frames at ``fps`` (rounded up)."""
        if event_type in self.min_event_seconds:
            return max(1, math.ceil(Fraction(str(self.min_event_seconds[event_type])) * fps))
        return self.min_event_frames.get(event_type, 1)

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
    # The model is not a profile value: one default for every profile (llm.DEFAULT_MODEL), another
    # one chosen at launch (--llm-model, --model, the interface).
    backend: Literal["ollama"]
    num_ctx: int
    temperature: float
    language: str


# --- root ---------------------------------------------------------------------------------


class Profile(_Model):
    # ``profile:`` was the name of this section before v3 (SPEC §12.2); still accepted.
    meta: ProfileMeta = Field(validation_alias=AliasChoices("meta", "profile"))
    format: Format
    video: Video
    audio: Audio
    structure: Structure
    rules: Rules
    llm: Llm


# --- field descriptions -----------------------------------------------------------------------
#
# French, read by people (explain-profile) and by the local model of draft-profile, which may
# only answer on these fields (SPEC §13). Kept here so that the model stays the single source.

_DESCRIPTIONS: dict[type[BaseModel], dict[str, str]] = {
    Format: {
        "codecs": "Codecs et profils de codec acceptés pour le fichier (ex. ProRes 422 HQ, DNxHR HQX, XAVC Intra Class 100)",
        "containers": "Conteneurs de fichier acceptés : mov, mp4, mxf (tout motif), mxf_op1a ou mxf_opatom",
        "bit_depth_allowed": "Profondeurs d'image acceptées en bits par composante (ex. 10)",
        "chroma_allowed": "Sous-échantillonnage de la chrominance accepté : 4:2:0, 4:2:2, 4:4:4, ou rgb (fichier RVB)",
        "pix_fmt": "Format de pixel FFmpeg attendu (ancienne forme, ex. yuv422p10le pour 4:2:2 10 bits)",
        "width": "Largeur de l'image en pixels (ex. 1920)",
        "height": "Hauteur de l'image en lignes (ex. 1080)",
        "fps_allowed": "Cadences d'images acceptées, en fractions 'num/den' (ex. '25/1', '50/1')",
        "field_order": "Balayage attendu : progressive, psf (progressif en deux trames), tt, bb, tb ou bt (entrelacé)",
        "color_primaries": "Primaires colorimétriques attendues (ex. bt709 ; coherent : cohérentes avec le fichier)",
        "color_transfer": "Fonction de transfert attendue (ex. bt709 ; coherent : cohérente avec le fichier)",
        "color_space": "Matrice de couleur attendue (ex. bt709 ; coherent : cohérente avec le fichier)",
        "color_range": "Plage de codage : tv (légale, 64-940 en 10 bits) ou pc (pleine)",
        "unknown_color_tags_severity": "Gravité si les balises de colorimétrie sont absentes",
        "letterbox": "Contrôle du format d'image (bandes noires) et lignes actives attendues par format",
        "delivery": "Format attendu par le diffuseur pour le fichier livré (balayage, cadences, codec de livraison)",
    },
    CodecSpec: {"codec_name": "Nom du codec selon ffprobe (ex. prores, dnxhd)",
                "profile": "Profil du codec selon ffprobe (ex. HQ, DNXHR HQX)",
                "label": "Nom du codec dans le document du client (ex. XAVC HD Intra Class 100)"},
    Letterbox: {"check": "Contrôler le format d'image et les bandes noires",
                "formats": "Formats d'image admis avec leurs lignes et pixels actifs",
                "tolerance_lines": "Tolérance en lignes sur le nombre de lignes actives"},
    LetterboxFormat: {"aspect": "Rapport d'image (ex. 1.85)", "active_lines": "Nombre de lignes actives",
                      "first_line": "Première ligne active (numérotation du document)",
                      "last_line": "Dernière ligne active (numérotation du document)",
                      "active_pixels": "Nombre de pixels actifs par ligne"},
    Delivery: {"scan": "Balayage du fichier livré : progressive, interlaced_tff, interlaced_bff ou psf",
               "fps": "Cadences d'images du fichier livré, en fractions 'num/den' (50i = '25/1' entrelacé)",
               "codec": "Codec et conteneur du fichier livré, tels que le document les nomme"},
    Video: {
        "bit_depth": "Profondeur de quantification vidéo en bits (10)",
        "y_min_legal": "Niveau du noir de la luminance Y en valeur de code 10 bits (ex. 64)",
        "y_max_legal": "Niveau du blanc nominal de la luminance Y en valeur de code 10 bits (ex. 940)",
        "y_tolerance_low_pct": "Tolérance basse de la luminance Y en pourcentage de la plage nominale (ex. -1)",
        "y_tolerance_high_pct": "Tolérance haute de la luminance Y en pourcentage de la plage nominale (ex. 103)",
        "rgb_min_pct": "Tolérance basse des composantes R, V, B en pourcentage (ex. -5)",
        "rgb_max_pct": "Tolérance haute des composantes R, V, B en pourcentage (ex. 105)",
        "max_out_of_range_area_pct": "Surface de l'image hors tolérance, en pourcentage : seuil d'erreur",
        "out_of_range_area_error": "Erreur si la surface hors tolérance dépasse strictement le seuil (above) ou l'atteint (at_least)",
        "prefilter": "Filtrer le signal avant la mesure des niveaux (dépassements fugitifs)",
        "prefilter_taps": "Nombre de coefficients du filtre horizontal avant mesure (3 ou 5)",
        "measure_spaces": "Espaces dans lesquels mesurer les niveaux : ycbcr, rgb",
        "scan_detection": "Paramètres de la détection de peignage (PAD Guard, pas une valeur de diffuseur)",
        "range_detection": "Paramètres de la détection d'un contenu en plage pleine (PAD Guard, pas une valeur de diffuseur)",
    },
    RangeDetection: {"reserved_min_frames_pct": "Part des images du programme atteignant les bornes de la plage "
                                                "numérique (4 et 1019) à partir de laquelle le contenu est en plage pleine"},
    ScanDetection: {"comb_ratio_min": "Rapport de peignage à partir duquel une image est peignée",
                    "motion_min": "Différence moyenne entre images à partir de laquelle une image bouge",
                    "interlaced_min_pct": "Part d'images peignées au-delà de laquelle le fichier est entrelacé",
                    "progressive_max_pct": "Part d'images peignées en deçà de laquelle le fichier est progressif",
                    "min_moving_frames": "Nombre minimal d'images en mouvement pour conclure"},
    Audio: {
        "sample_rate": "Fréquence d'échantillonnage audio en Hz (ex. 48000)",
        "bit_depth": "Quantification audio en bits (ex. 24)",
        "bit_depth_allowed": "Quantifications audio acceptées en bits (ex. [24, 16])",
        "same_bit_depth_all_tracks": "Toutes les pistes doivent avoir la même quantification",
        "channel_layout": "Organisation des pistes : stereo_pairs (pistes gérées par paires AES)",
        "max_pairs": "Nombre maximal de paires audio AES",
        "no_silent_tracks": "Interdiction des pistes sans contenu (silence)",
        "silent_track_dbfs": "Niveau en dBFS sous lequel une piste entière est considérée sans contenu",
        "dual_mono_must_be_identical": "Une version mono doit être livrée en double mono identique et en phase",
        "groups": "Affectation des pistes audio (nom de version, numéros de pistes, stéréo/mono/5.1, obligatoire)",
        "loudness_exempt_groups": "Groupes audio exemptés de l'excursion short term (sans dialogue)",
        "loudness": "Valeurs de loudness (intensité sonore) du programme",
        "true_peak_max_dbtp": "Niveau crête vrai (true peak) maximal en dBTP (ex. -1 ou -3)",
        "alignment_tone": "Signal d'alignement : fréquence en Hz et niveau en dBFS (ex. 1000 Hz à -18 dBFS)",
        "silence_dbfs": "Niveau en dBFS sous lequel le son est un silence",
        "silence_max_seconds": "Durée maximale d'un silence dans le programme, en secondes",
        "phase_min_correlation": "Corrélation de phase stéréo minimale admise",
        "phase_min_seconds": "Durée en secondes au-delà de laquelle une opposition de phase est signalée",
        "av_sync_ms": "Tolérance de synchronisation son/image en millisecondes (avance et retard du son)",
        "exclude_head_tail": "Exclure la tête et la queue (mire, noirs) des mesures audio",
    },
    AudioGroup: {"name": "Nom de la version audio (ex. VF, VO, VI)", "tracks": "Numéros des pistes (canaux), à partir de 1",
                 "layout": "mono, dual_mono, stereo ou 5.1", "required": "Version obligatoire"},
    Loudness: {"method": "Méthode et norme de mesure du loudness (ex. EBU R 128, ITU-R BS.1770)",
               "long_program_min_seconds": "Durée en secondes au-delà de laquelle un programme est « long »",
               "long": "Valeurs de loudness des programmes longs (ou de tous les programmes)",
               "short": "Valeurs de loudness des programmes courts (bandes annonces, messages)"},
    LoudnessRules: {"integrated_lufs": "Loudness intégré cible du programme en LUFS (ex. -23)",
                    "integrated_tolerance_lu": "Tolérance autour du loudness intégré cible, en LU (ex. 1 pour ± 1 LU)",
                    "lra_max_lu": "Plage de loudness (LRA) maximale en LU",
                    "lra_recommended_range_lu": "Plage de LRA recommandée en LU [min, max] (information)",
                    "short_term_dialogue_excursion_lu": "Excursion admise du loudness short term (3 s) autour de la cible pour le dialogue, en LU",
                    "short_term_max_lufs": "Loudness short term (3 s) maximal en LUFS",
                    "short_term_excursion_above_lu": "Excursion maximale du short term au-dessus de la cible, en LU"},
    Tone: {"hz": "Fréquence du signal d'alignement en Hz", "dbfs": "Niveau du signal d'alignement en dBFS"},
    AvSync: {"audio_early_max": "Avance maximale du son sur l'image, en ms",
             "audio_late_max": "Retard maximal du son sur l'image, en ms"},
    Structure: {"leaders": "Amorces : classic (mire, noirs de tête et de queue) ou none (aucune amorce)",
                "timecode": "Timecode du fichier et du début du programme",
                "bars": "Mire de barres et signal 1 kHz en tête",
                "black": "Noirs et silences de tête et de queue",
                "freeze": "Détection des images figées (PAD Guard)",
                "pse": "Contrôle des flashs (épilepsie photosensible)",
                "first_frames": "Contraintes sur les premières images (sous-titres)",
                "logo": "Présence de logo dans le programme",
                "credits": "Génériques de fin",
                "safe_areas": "Zones de sécurité des titres et sous-titres"},
    TimecodeRules: {"file_start": "Timecode de la première image du fichier, HH:MM:SS:FF",
                    "program_start": "Timecode de la première image du programme, HH:MM:SS:FF (ex. 10:00:00:00)",
                    "tolerance_frames": "Tolérance en images sur le début du programme",
                    "drop_frame_allowed": "Timecode drop frame autorisé",
                    "must_be_continuous": "Timecode continu, sans saut ni recouvrement"},
    Bars: {"required": "Mire de barres obligatoire en tête", "forbidden": "Mire interdite dans le fichier",
           "start_tc": "Timecode de début de la mire, HH:MM:SS:FF", "min_seconds": "Durée minimale de la mire, en secondes",
           "pattern": "Type de mire : ebu_75, ebu_100 ou smpte_hd", "tone_hz": "Fréquence du son de mire en Hz",
           "tone_dbfs": "Niveau du son de mire en dBFS", "tone_tolerance_db": "Tolérance sur le niveau du son de mire, en dB",
           "tolerance": "Erreur moyenne admise pour reconnaître la mire (PAD Guard)"},
    Black: {"head_min_seconds": "Durée minimale du noir de tête, en secondes",
            "tail_min_seconds": "Durée minimale du noir de queue, en secondes",
            "head_max_seconds": "Durée maximale du noir de tête, en secondes (sans amorce)",
            "tail_max_seconds": "Durée maximale du noir de queue, en secondes (sans amorce)",
            "y_max": "Valeur de code 10 bits sous laquelle une image est noire (PAD Guard)",
            "silence_dbfs": "Niveau en dBFS sous lequel le son du noir est un silence"},
    Freeze: {"threshold": "Différence moyenne sous laquelle deux images sont identiques (PAD Guard)",
             "min_seconds": "Durée minimale d'une image figée signalée, en secondes"},
    Pse: {"enabled": "Contrôle des flashs activé", "max_flashes_per_second": "Nombre maximal de flashs par seconde",
          "flash_min_delta_pct": "Variation de luminance minimale d'un flash, en pourcentage",
          "flash_min_area_pct": "Surface minimale d'un flash, en pourcentage de l'image"},
    FirstFrames: {"no_subtitles_first_frames": "Nombre de premières images sans sous-titre"},
    Logo: {"forbidden": "Logo de chaîne interdit dans le programme"},
    Credits: {"end_credits_max_seconds": "Durée maximale du générique de fin par genre, en secondes",
              "silent_black_credits_forbidden": "Générique silencieux sur noir interdit"},
    SafeAreas: {"title_safe_pct": "Marges de sécurité des titres en pourcentage (horizontal, vertical)",
                "subtitle_safe": "Zone de sécurité des sous-titres", "logo_corners_free": "Coins de l'image libres pour le logo"},
    TitleSafe: {"horizontal": "Marge horizontale en pourcentage", "vertical": "Marge verticale en pourcentage"},
}
for _model, _fields in _DESCRIPTIONS.items():
    for _name, _text in _fields.items():
        _model.model_fields[_name].description = _text


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


def translate(err: dict[str, Any], prefix: str = "") -> str:
    """French message for one pydantic error; ``prefix`` is prepended to its location."""
    where = prefix + _loc(err["loc"]) or "(racine)"
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
    """Effective profile of the YAML file at ``path``, with the norms it extends (SPEC §12.3)."""
    from pad_guard.profiles import resolve_profile  # the resolver imports this module

    return resolve_profile(path).profile


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
