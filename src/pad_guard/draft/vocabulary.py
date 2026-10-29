"""What a quote must say for a value to be taken for a field (deterministic check, SPEC §13).

A real quote and a matching number are not enough: a local model readily pairs a field with a
sentence that holds the right number for another reason (the alignment tone at -18 dBFS taken
for the silence threshold). So each field has its vocabulary (every group of words must appear
in the quote, accents and case ignored) and, for numbers, its unit, which must follow the number
in the quote. Internal PAD Guard parameters never come from a broadcaster document.
"""

from __future__ import annotations

import re
import unicodedata

# Parameters of the tool or of the Lumiris master, not of the broadcaster's delivery.
INTERNAL = frozenset({
    "format.codecs", "format.containers", "format.unknown_color_tags_severity", "format.letterbox.check",
    "format.letterbox.tolerance_lines", "video.prefilter_taps", "video.scan_detection.comb_ratio_min",
    "video.scan_detection.motion_min", "video.scan_detection.interlaced_min_pct",
    "video.scan_detection.progressive_max_pct", "video.scan_detection.min_moving_frames",
    "audio.loudness_exempt_groups", "audio.exclude_head_tail", "structure.bars.tolerance", "structure.black.y_max",
    "structure.freeze.threshold", "video.range_detection.reserved_min_frames_pct",
})

_FPS = r"images? par seconde|images?/s|i/s|fps|frequence image|cadence|frame rate|\d\s*p\b|\d\s*i\b|psf"
_SCAN = r"balayage|progressi|entrelac|interlac|scan|psf"
_COLOUR = r"709|2020|colorim|primaires|gamma|espace"
_LOUD = r"loudness|lufs|lkfs|integr|intensite sonore"
_SHORT_TERM = r"short.?term|court terme"
_HEAD = r"tete|debut|head|en amont|avant"
_TAIL = r"queue|fin\b|tail|apres"

# Every pattern of the tuple must match the normalised quote.
KEYWORDS: dict[str, tuple[str, ...]] = {
    "format.pix_fmt": (r"4[:.]2[:.]2|10.?bits?",),
    "format.bit_depth_allowed": (r"bits?|quantif",),
    "format.chroma_allowed": (r"4[:.][24][:.][024]|chromin|echantillonnage|sampling|rvb|rgb",),
    "format.width": (r"\d{3,4} ?x ?\d{3,4}|resolution|definition|pixels",),
    "format.height": (r"\d{3,4} ?x ?\d{3,4}|resolution|definition|lignes",),
    "format.fps_allowed": (_FPS,),
    "format.field_order": (_SCAN,),
    "format.color_primaries": (_COLOUR,),
    "format.color_transfer": (_COLOUR,),
    "format.color_space": (_COLOUR,),
    "format.color_range": (r"\b64\b|\b940\b|\b16\b|\b235\b|plage|range|legal",),
    "format.letterbox.formats": (r"lignes? (actives|utiles)|format d.image|1[.,]85|2[.,]35|1[.,]77",),
    "format.delivery.scan": (_SCAN,),
    "format.delivery.fps": (_FPS,),
    "format.delivery.codec": (r"codec|xavc|prores|dnx|avc|h.?264|mxf|class",),
    "video.bit_depth": (r"bits?|quantif",),
    "video.y_min_legal": (r"\b64\b|noir|black",),
    "video.y_max_legal": (r"\b940\b|blanc|white",),
    "video.y_tolerance_low_pct": (r"luminance|\by\b",),
    "video.y_tolerance_high_pct": (r"luminance|\by\b",),
    "video.rgb_min_pct": (r"rvb|rgb|composantes",),
    "video.rgb_max_pct": (r"rvb|rgb|composantes",),
    "video.max_out_of_range_area_pct": (r"surface|superficie|area|de l.image",),
    "video.out_of_range_area_error": (r"surface|superficie|area|de l.image|of the image|nombre total de pixels",),
    "video.prefilter": (r"filtr",),
    "video.measure_spaces": (r"rvb|rgb|ycbcr|ycrcb|espaces?",),
    "audio.sample_rate": (r"khz|hz|echantillonnage|frequence",),
    "audio.bit_depth": (r"bits?|quantif",),
    "audio.bit_depth_allowed": (r"bits?|quantif",),
    "audio.same_bit_depth_all_tracks": (r"quantif|bits?",),
    "audio.channel_layout": (r"paires?|aes",),
    "audio.max_pairs": (r"paires?|pistes",),
    "audio.no_silent_tracks": (r"silenc|sans contenu",),
    "audio.silent_track_dbfs": (r"pistes?", r"silenc|sans contenu"),
    "audio.dual_mono_must_be_identical": (r"mono",),
    "audio.groups": (r"pistes?|tracks?|canal|canaux|channels?",),
    "audio.loudness.method": (r"r ?128|1770|3341|3342|3343|3344|ebu",),
    "audio.loudness.long_program_min_seconds": (r"duree|programmes?|minutes?",),
    "audio.loudness.long.integrated_lufs": (_LOUD,),
    "audio.loudness.long.integrated_tolerance_lu": (r"toleran|±|\+/-",),
    "audio.loudness.long.lra_max_lu": (r"lra|loudness range",),
    "audio.loudness.long.lra_recommended_range_lu": (r"lra|loudness range",),
    "audio.loudness.long.short_term_dialogue_excursion_lu": (_SHORT_TERM, r"dialogue"),
    "audio.loudness.long.short_term_max_lufs": (_SHORT_TERM,),
    "audio.loudness.long.short_term_excursion_above_lu": (_SHORT_TERM, r"excursion|au.dessus|\+"),
    "audio.loudness.short.integrated_lufs": (_LOUD,),
    "audio.loudness.short.integrated_tolerance_lu": (r"toleran|±|\+/-",),
    "audio.loudness.short.lra_max_lu": (r"lra|loudness range",),
    "audio.loudness.short.lra_recommended_range_lu": (r"lra|loudness range",),
    "audio.loudness.short.short_term_dialogue_excursion_lu": (_SHORT_TERM, r"dialogue"),
    "audio.loudness.short.short_term_max_lufs": (_SHORT_TERM,),
    "audio.loudness.short.short_term_excursion_above_lu": (_SHORT_TERM, r"excursion|au.dessus|\+"),
    "audio.true_peak_max_dbtp": (r"true.?peak|crete|\btp\b|dbtp",),
    "audio.alignment_tone.hz": (r"alignement|sinus|signal de reference|line.?up",),
    "audio.alignment_tone.dbfs": (r"alignement|sinus|signal de reference|line.?up",),
    "audio.silence_dbfs": (r"silence",),
    "audio.silence_max_seconds": (r"silence",),
    "audio.phase_min_correlation": (r"phase|correlation",),
    "audio.phase_min_seconds": (r"phase|correlation",),
    "audio.av_sync_ms.audio_early_max": (r"synchro|lip|avance|decalage",),
    "audio.av_sync_ms.audio_late_max": (r"synchro|lip|retard|decalage",),
    "structure.leaders": (r"amorces?|leaders?|clap|decompte|mire",),
    "structure.timecode.file_start": (r"timecode|time code|\btc\b",),
    "structure.timecode.program_start": (r"timecode|time code|\btc\b",),
    # A tolerance must be said: « affichage d'au moins 5 images » (subtitle timecodes) is not one.
    "structure.timecode.tolerance_frames": (r"timecode|time code|\btc\b", r"images?|frames?",
                                            r"toleran|\bpres\b|precision|precis|ecart|accura"),
    "structure.timecode.drop_frame_allowed": (r"drop",),
    "structure.timecode.must_be_continuous": (r"continu|saut|recouvrement|discontinu",),
    "structure.bars.required": (r"mire|barres|bars",),
    "structure.bars.forbidden": (r"mire|barres|bars|amorces?",),
    "structure.bars.start_tc": (r"mire|barres|bars",),
    "structure.bars.min_seconds": (r"mire|barres|bars",),
    "structure.bars.pattern": (r"mire|barres|bars",),
    "structure.bars.tone_hz": (r"mire|barres|bars|1 ?khz|1[. ]?000 ?hz",),
    "structure.bars.tone_dbfs": (r"mire|barres|bars|1 ?khz|1[. ]?000 ?hz",),
    "structure.bars.tone_tolerance_db": (r"mire|barres|bars|1 ?khz|1[. ]?000 ?hz", r"toleran|±|\+/-"),
    "structure.black.head_min_seconds": (r"noir|black", _HEAD),
    "structure.black.tail_min_seconds": (r"noir|black", _TAIL),
    "structure.black.head_max_seconds": (r"noir|black", _HEAD),
    "structure.black.tail_max_seconds": (r"noir|black", _TAIL),
    "structure.black.silence_dbfs": (r"silence", r"noir|black"),
    "structure.freeze.min_seconds": (r"fige|freeze|gel",),
    "structure.pse.enabled": (r"flash|epilep|\bpse\b|harding|clignot|photosensib",),
    "structure.pse.max_flashes_per_second": (r"flash|epilep|\bpse\b|harding|clignot|photosensib",),
    "structure.pse.flash_min_delta_pct": (r"flash|epilep|\bpse\b|harding|clignot|photosensib",),
    "structure.pse.flash_min_area_pct": (r"flash|epilep|\bpse\b|harding|clignot|photosensib",),
    "structure.first_frames.no_subtitles_first_frames": (r"sous.?titre",),
    "structure.logo.forbidden": (r"logo",),
    "structure.credits.end_credits_max_seconds": (r"generique",),
    "structure.credits.silent_black_credits_forbidden": (r"generique",),
    "structure.safe_areas.title_safe_pct.horizontal": (r"securite|safe|marges?",),
    "structure.safe_areas.title_safe_pct.vertical": (r"securite|safe|marges?",),
    # A zone must be said: « 65 signes au maximum » (subtitle line length) is not a safe area.
    "structure.safe_areas.subtitle_safe": (r"sous.?titre|subtitle|caption",
                                           r"securite|safe|zone|cadre|marge|position"),
    "structure.safe_areas.logo_corners_free": (r"logo|coins?",),
}

# Unit written after the number, by suffix of the field name (checked on numeric values only).
UNITS: tuple[tuple[str, str], ...] = (
    ("_dbfs", r"db ?fs"), ("_lufs", r"lufs|lkfs"), ("_dbtp", r"db ?tp|dbtp"), ("_pct", r"%|pour ?cent"),
    ("_lu", r"lu\b|lufs"), ("_ms", r"ms\b|milli"), ("_db", r"db\b"),
    (".dbfs", r"db ?fs"), (".hz", r"k?hz"), ("_hz", r"k?hz"), ("sample_rate", r"k?hz"),
    ("bit_depth", r"-? ?bits?"), ("bit_depth_allowed", r"-? ?bits?"), ("max_pairs", r"paires?"),
)


# A negation or a prohibition in the quote.
NEGATION = (r"\bne\b.{0,60}\b(pas|jamais|aucun)|\bn'.{0,60}\b(pas|jamais|aucun)|interdit|proscrit|\baucune?\b|"
            r"\bsans\b|\bjamais\b|\bpas d(e|')|\bpas de\b|\bno\b|\bnot\b|forbidden")
_INTERLACED = r"entrelac|interlac|\d\s*i\b"
_UPPER_FIRST = r"(upper|top|superieure?|haute) field first|\b(tff|uff)\b|trame (superieure|haute) en premier"
_LOWER_FIRST = r"(lower|bottom|inferieure?|basse) field first|\b(bff|lff)\b|trame (inferieure|basse) en premier"

# For choices and yes/no values, what the quote must say (and must not say) for that value:
# {path: {value as JSON: (required pattern or None, forbidden pattern or None)}}.
EVIDENCE: dict[str, dict[str, tuple[str | None, str | None]]] = {
    "structure.leaders": {
        '"none"': (r"(" + NEGATION + r").{0,60}amorce|amorce.{0,60}(" + NEGATION + r")", None),
        '"classic"': (r"amorce|mire|decompte|noir de tete", NEGATION),
    },
    "structure.bars.required": {"true": (r"mire|barres", NEGATION), "false": (NEGATION, None)},
    "structure.bars.forbidden": {"true": (NEGATION, None), "false": (None, NEGATION)},
    # « Upper / top field first » is tt, « lower / bottom field first » is bb; tb and bt (coded in one
    # order, shown in the other) are never what such a sentence means.
    "format.field_order": {'"progressive"': (r"progressi", None),
                           '"tt"': (_INTERLACED, _LOWER_FIRST), '"bb"': (_INTERLACED, _UPPER_FIRST),
                           '"tb"': (_INTERLACED, _UPPER_FIRST + "|" + _LOWER_FIRST),
                           '"bt"': (_INTERLACED, _UPPER_FIRST + "|" + _LOWER_FIRST)},
    "format.delivery.scan": {'"progressive"': (r"progressi", None), '"interlaced_tff"': (_INTERLACED, None),
                             '"interlaced_bff"': (_INTERLACED, None), '"psf"': (r"psf|segment", None)},
    "format.color_range": {'"tv"': (r"limit|narrow|legal|nominal|64|16", r"full|pleine"),
                           '"pc"': (r"full|pleine", None)},
    "structure.pse.enabled": {"true": (None, NEGATION), "false": (NEGATION, None)},
    # « ne doit pas excéder 1 % », « exceeds 1% »: strictly above; « au moins 1 % »: from the threshold on.
    "video.out_of_range_area_error": {'"above"': (r"exced|depass|exceed|au.dela|plus de|superieure? a", r"au moins|at least"),
                                      '"at_least"': (r"au moins|at least|atteint|reach", None)},
    "video.prefilter": {"true": (None, r"\bne\b.{0,40}\bpas\b.{0,20}filtr|sans filtr"), "false": (NEGATION, None)},
    "structure.timecode.drop_frame_allowed": {"true": (None, NEGATION), "false": (NEGATION, None)},
    **{f"format.{k}": {'"bt709"': (r"709", None), '"bt2020"': (r"2020", None), '"smpte2084"': (r"2084|pq", None),
                       '"arib-std-b67"': (r"hlg|b67", None)}
       for k in ("color_primaries", "color_transfer", "color_space")},
}

# Free-text values that must be written in the quote itself (accents, case and spaces ignored).
LITERAL_TEXT = frozenset({"audio.loudness.method", "format.delivery.codec", "structure.safe_areas.subtitle_safe"})


def _yes_no_default(path: str) -> dict[str, tuple[str | None, str | None]] | None:
    """Prohibitions (forbidden, no_…) need a negation in the quote to be true, and none to be false."""
    name = path.rsplit(".", 1)[-1]
    if "forbidden" in name or name.startswith("no_"):
        return {"true": (NEGATION, None), "false": (None, NEGATION)}
    return None


def evidence(path: str, value_json: str, quote: str) -> str | None:
    """None if the quote supports this choice / yes-no value, else a French reason."""
    rules = EVIDENCE.get(path) or _yes_no_default(path)
    if not rules or value_json not in rules:
        return None
    need, refuse = rules[value_json]
    text = plain(quote)
    if need and not re.search(need, text):
        return f"la citation ne dit pas {value_json} pour ce champ"
    if refuse and re.search(refuse, text):
        return f"la citation contredit la valeur {value_json} (négation ou terme contraire)"
    return None


def plain(text: str) -> str:
    """Accents removed, case folded, typographic apostrophes made plain."""
    decomposed = unicodedata.normalize("NFKD", text.replace("’", "'").replace("‘", "'"))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def missing_words(path: str, quote: str) -> str | None:
    """None if the quote has the vocabulary of the field, else the expected words (French)."""
    text = plain(quote)
    for pattern in KEYWORDS.get(path, ()):
        if not re.search(pattern, text):
            return pattern.replace("\\b", "").replace("\\", "")
    return None


def unit_of(path: str) -> str | None:
    name = path.rsplit(".", 1)[-1]
    for suffix, pattern in UNITS:
        if path.endswith(suffix) or name == suffix.lstrip("._"):
            return pattern
    return None
