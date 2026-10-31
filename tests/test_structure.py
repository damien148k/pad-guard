from __future__ import annotations

import numpy as np
import pytest

from pad_guard.rules.engine import error_key, merge
from pad_guard.rules.profile import LetterboxFormat, Letterbox, ProfileValueError, load_profile, require
from pad_guard.structure import detect, letterbox as lb
from pad_guard.structure.models import LetterboxSample

from conftest import PROFILES, TEST_PROFILES

NAN = np.nan


def test_runs() -> None:
    assert detect.runs(np.array([0, 1, 1, 0, 1, 0, 0, 1], bool)) == [(1, 2), (4, 4), (7, 7)]
    assert detect.runs(np.zeros(3, bool)) == [] and detect.runs(np.ones(2, bool)) == [(0, 1)]
    mask = np.array([1, 1, 0, 1, 1, 1], bool)
    assert detect.leading_run(mask) == (0, 1) and detect.trailing_run(mask) == (3, 5)
    assert detect.run_ending_at(mask, 4) == (3, 4) and detect.run_ending_at(mask, 2) is None


def test_frozen_ranges_include_the_first_held_frame() -> None:
    # Frames 3..8 show the same picture: frames 4..8 are static (equal to the previous one).
    d = np.array([NAN, 5, 5, 5, 0, 0, 0, 0, 0, 5, 5], float)
    static = detect.static(d, 0.5)
    none = np.zeros(d.size, bool)
    assert detect.frozen_ranges(static, none, 6) == [(3, 8)]
    assert detect.frozen_ranges(static, none, 7) == []
    excluded = none.copy()
    excluded[6] = True  # an excluded frame (black, bars) splits the freeze
    assert detect.frozen_ranges(static, excluded, 2) == [(3, 5), (7, 8)]


def test_duplicates_need_movement_around() -> None:
    d = np.array([NAN, 4, 4, 0, 4, 4, 0, 0, 4], float)
    assert detect.duplicates(d, 0.5, np.zeros(d.size, bool)) == [3]  # 6-7 is a 3-frame hold, not a duplicate


def test_isolated_black_ignores_fades() -> None:
    black = np.zeros(20, bool)
    y_mean = np.full(20, 400.0)
    black[5] = True  # cut to black for one frame
    y_mean[5] = 64
    black[12] = True  # end of a fade out: 400 -> 300 -> 200 -> 64
    y_mean[9:13] = [400, 300, 200, 64]
    assert detect.isolated_black(black, y_mean) == [5]
    black[5:7] = True  # two black frames are not "isolated"
    y_mean[9:13] = 400  # no fade any more before frame 12
    assert detect.isolated_black(black, y_mean) == [12]


def _flashes(period: int, frames: int = 50) -> tuple[np.ndarray, np.ndarray]:
    """Full-screen black/white alternation every ``period`` frames."""
    up = np.zeros(frames)
    down = np.zeros(frames)
    for k in range(period, frames, period):
        (up if (k // period) % 2 else down)[k] = 100.0
    return up, down


def test_flash_ranges() -> None:
    up, down = _flashes(2)  # a transition every 2 frames: 12 transitions per second, 6 flashes
    ((a, b, worst),) = detect.flash_ranges(up, down, 25.0, 25, 3)
    assert worst == 6 and a == 2
    up, down = _flashes(4)  # 6 transitions per second: 3 flashes, allowed
    assert detect.flash_ranges(up, down, 25.0, 25, 3) == []
    up, down = _flashes(2)
    assert detect.flash_ranges(up * 0.2, down * 0.2, 25.0, 25, 3) == []  # 20 % of the picture only


def test_flash_spread_over_two_frames_counts_once() -> None:
    up = np.zeros(30)
    down = np.zeros(30)
    up[[2, 3, 10, 11, 18, 19]] = 50.0  # each brightening takes two frames
    down[[6, 14, 22]] = 50.0
    assert detect.flash_ranges(up, down, 25.0, 25, 2) == [(3, 22, 3)]  # 6 transitions = 3 flashes


def test_merge_gap_counts_clean_frames() -> None:
    assert merge([(0, 2), (14, 15)], 12) == [(0, 15)]  # frames 3..13: 11 clean frames, fewer than 12
    assert merge([(0, 2), (15, 15)], 12) == [(0, 2), (15, 15)]  # 12 clean frames: separate events
    assert merge([(5, 9), (0, 3)], 0) == [(0, 3), (5, 9)]


def test_error_key_deduplicates_exception_and_log() -> None:
    log = "prores: invalid frame header"
    exc = ("[Errno 1094995529] Invalid data found when processing input: 'avcodec_send_packet()'; "
           "last error log: [prores] invalid frame header")
    assert error_key(log) == error_key(exc) == "prores: invalid frame header"
    assert error_key("[Errno 5] something else") == "something else"


def _frame_with_bands(top: int, bottom: int, left: int = 0, right: int = 1919) -> np.ndarray:
    y = np.full((1080, 1920), 64, np.uint16)
    y[top: bottom + 1, left: right + 1] = 500
    y[0, 0] = 900  # a single bright pixel in a black band does not make the row active
    return y


def test_letterbox_classification() -> None:
    spec = Letterbox(check=True, tolerance_lines=2, formats=[
        LetterboxFormat(aspect="1.77", active_lines=1080, first_line=21, last_line=1123, active_pixels=1920),
        LetterboxFormat(aspect="1.85", active_lines=1036, first_line=32, last_line=1112, active_pixels=1920),
        LetterboxFormat(aspect="2.35", active_lines=816, first_line=87, last_line=1057, active_pixels=1920),
        LetterboxFormat(aspect="1.33", active_lines=1080, first_line=21, last_line=1123, active_pixels=1440),
    ])
    s = lb.active_area(_frame_with_bands(22, 1057), 0, 68)
    assert (s.top, s.bottom, lb.lines(s), lb.pixels(s)) == (22, 1057, 1036, 1920)
    assert lb.classify(s, spec, 2, 1920, 1080) == "1.85"
    assert lb.classify(lb.active_area(_frame_with_bands(132, 947), 1, 68), spec, 2, 1920, 1080) == "2.35"
    assert lb.classify(lb.active_area(_frame_with_bands(0, 1079, 240, 1679), 2, 68), spec, 2, 1920, 1080) == "1.33"
    assert lb.classify(lb.active_area(_frame_with_bands(100, 979), 3, 68), spec, 2, 1920, 1080) is None
    assert lb.active_area(np.full((1080, 1920), 64, np.uint16), 4, 68) is None


def test_blanking_deviation_edge_by_edge() -> None:
    f185 = LetterboxFormat(aspect="1.85", active_lines=1036, first_line=32, last_line=1112, active_pixels=1920)
    f235 = LetterboxFormat(aspect="2.35", active_lines=816, first_line=87, last_line=1057, active_pixels=1920)
    spec = Letterbox(check=True, tolerance_lines=2, formats=[f185, f235])
    # Arte §3.2.4, SMPTE 274M interlaced numbering (field 1: lines 21-560, field 2: 584-1123): the first
    # and last lines of each format are the rows of the format centred in the frame.
    for f in (f185, f235):
        assert lb.expected_boxes(f, 1920, 1080) == [((f.first_line - 21) * 2, (f.last_line - 584) * 2 + 1, 0, 1919)]
    exact, one, three = (lb.active_area(_frame_with_bands(22 + k, 1057 + k), 0, 68) for k in (0, 1, 3))
    assert lb.deviation(exact, f185, 1920, 1080) == (0, (22, 1057, 0, 1919))
    assert lb.deviation(one, f185, 1920, 1080)[0] == 1 and lb.classify(one, spec, 2, 1920, 1080) == "1.85"
    assert lb.deviation(three, f185, 1920, 1080)[0] == 3 and lb.classify(three, spec, 2, 1920, 1080) is None
    # The same number of lines, shifted by 3: the count alone said 1.85.
    assert lb.lines(three) == 1036
    # One column short on the right is a deviation too.
    narrow = lb.active_area(_frame_with_bands(22, 1057, 0, 1918), 0, 68)
    assert lb.nearest(narrow, spec, 1920, 1080)[:2] == (f185, 1)
    # An odd number of black lines: either placement is exact.
    odd = LetterboxFormat(aspect="x", active_lines=1077, first_line=0, last_line=0, active_pixels=1920)
    assert [b[:2] for b in lb.expected_boxes(odd, 1920, 1080)] == [(1, 1077), (2, 1078)]
    assert lb.deviation(lb.active_area(_frame_with_bands(2, 1078), 0, 68), odd, 1920, 1080)[0] == 0


def test_codec_ringing_does_not_move_the_edge() -> None:
    """ProRes / DNxHR 8x8 blocks ring into the band rows that share a block with the picture (measured on
    ProRes HQ: up to 82 on 128 pixels of a row); the edge stays on the exact line."""
    y = _frame_with_bands(22, 1057)
    y[16:22, ::15] = 82
    s = lb.active_area(y, 0, 68)
    assert (s.top, s.bottom) == (22, 1057)


def test_letterbox_dominant_and_changes() -> None:
    spec = Letterbox(check=True, tolerance_lines=2, formats=[
        LetterboxFormat(aspect="1.85", active_lines=1036, first_line=32, last_line=1112, active_pixels=1920),
        LetterboxFormat(aspect="2.35", active_lines=816, first_line=87, last_line=1057, active_pixels=1920)])
    wide = [lb.active_area(_frame_with_bands(132, 947), f, 68) for f in (40, 50, 60)]
    normal = [lb.active_area(_frame_with_bands(22, 1057), f, 68) for f in (0, 10, 20, 30, 70, 80, 90)]
    dark = [lb.active_area(_frame_with_bands(300, 700), f, 68) for f in (31, 32, 33, 34, 35)]  # inside: no change
    samples = sorted(normal + dark + wide, key=lambda s: s.frame)
    dom, share = lb.dominant(samples, 2)
    assert lb.lines(dom) == 1036 and share == 100.0  # every sample fits within the 1.85 area
    assert lb.format_changes(samples, spec, 2, dom, 1920, 1080) == []  # 2.35 inside 1.85: a dark-looking 2.35 shot
    full = [lb.active_area(_frame_with_bands(0, 1079), f, 68) for f in (41, 42, 43)]  # spills over the bands
    samples = sorted(normal + full, key=lambda s: s.frame)
    assert lb.format_changes(samples, spec, 2, dom, 1920, 1080) == [(41, 43, None, 3)]


def test_require_reports_null_and_missing() -> None:
    arte = load_profile(PROFILES / "arte_hd_sdr.yaml")
    assert require(arte, "structure.bars.tolerance", "x") == 12
    with pytest.raises(ProfileValueError, match="ne renseigne pas « structure.bars.pattern »"):
        require(arte, "structure.bars.pattern", "la mire")
    classic = load_profile(TEST_PROFILES / "test_classic.yaml")
    with pytest.raises(ProfileValueError, match="ne renseigne pas « format.letterbox »"):
        require(classic, "format.letterbox.tolerance_lines", "le format")
    nulled = classic.model_copy(deep=True)
    nulled.audio.silence_max_seconds = None
    nulled.audio.model_fields_set.add("silence_max_seconds")
    with pytest.raises(ProfileValueError, match="vaut null"):
        require(nulled, "audio.silence_max_seconds", "les silences")


def test_blanking_reference_taken_over_the_programme() -> None:
    f185 = LetterboxFormat(aspect="1.85", active_lines=1036, first_line=32, last_line=1112, active_pixels=1920)
    f177 = LetterboxFormat(aspect="1.77", active_lines=1080, first_line=21, last_line=1123, active_pixels=1920)
    spec = Letterbox(check=True, tolerance_lines=2, formats=[f177, f185])

    def area(frame, top, bottom, left=0, right=1919):
        return LetterboxSample(frame=frame, top=top, bottom=bottom, left=left, right=right)

    bright = [area(f, 22, 1057) for f in (5, 50, 95)]
    # Night: the sky loses 2 rows on most samples (within the tolerance), or 1 to 6 rows, scattered.
    steady = [area(f, 24, 1056) for f in range(0, 100, 2) if f != 50]
    scattered = [area(f, 23 + f % 6, 1056) for f in range(0, 100, 2) if f != 50]
    for night in (steady, scattered):
        ref, share = lb.reference(sorted(night + bright, key=lambda s: s.frame), spec, 2, 1920, 1080)
        assert (ref.top, ref.bottom, ref.left, ref.right) == (22, 1057, 0, 1919) and share == 100.0
    # The limit: 3 rows lost on most samples reads as another area (dark rows look like blanking).
    night = [area(f, 25, 1056) for f in range(0, 100, 2) if f != 50]
    assert lb.reference(night + bright, spec, 2, 1920, 1080)[0].top == 25
    # A flash ringing into the band on two samples, one column lost on a few: the edges do not move.
    flash = [area(7, 21, 1058), area(9, 21, 1057)]
    dim = [area(f, 22, 1057, 1, 1919) for f in (11, 13)]
    ref, _ = lb.reference(bright + flash + dim, spec, 2, 1920, 1080)
    assert (ref.top, ref.bottom, ref.left) == (22, 1057, 0)
    # Picture one line into the band on most samples: that is the edge (house anomaly).
    ref, _ = lb.reference([area(f, 21, 1057) for f in range(6)] + bright, spec, 2, 1920, 1080)
    assert lb.deviation(ref, f185, 1920, 1080)[0] == 1
    # A 1.77 section in a 1.85 programme: the reference stays 1.85, the section is a change.
    film = [area(f, 22, 1057) for f in range(0, 200, 10)]
    section = [area(f, 0, 1079) for f in (201, 202, 203)]
    samples = film + section
    ref, _ = lb.reference(samples, spec, 2, 1920, 1080)
    assert (ref.top, ref.bottom) == (22, 1057)
    assert lb.format_changes(samples, spec, 2, ref, 1920, 1080) == [(201, 203, "1.77", 3)]
    # No sample fits a format of the profile: the most frequent area, as before.
    odd = [area(f, 136, 943) for f in range(5)] + [area(9, 128, 943)]
    assert lb.reference(odd, spec, 2, 1920, 1080)[0].top == 136
    # The real Arte master: a 2.39 picture (808 lines) and a few full-frame cards that fit 1.77.
    cards = [area(f, 0, 1079, 1, 1917) for f in range(100, 104)]
    assert lb.reference(odd + cards, spec, 2, 1920, 1080)[0].top == 136


def _edge_columns(areas, mean=500.0):
    """a_* columns of the measurement pass for a list of (top, bottom, left, right) or None (black frame);
    ``mean``: luma of the edge rows and columns (a number, or a list per frame)."""
    means = mean if isinstance(mean, list) else [mean] * len(areas)
    cols = {k: [] for k in ("a_t", "a_b", "a_l", "a_r", "a_tm", "a_bm", "a_lm", "a_rm")}
    for a, m in zip(areas, means):
        for k, v in zip(("a_t", "a_b", "a_l", "a_r"), a or (np.nan,) * 4):
            cols[k].append(v)
        for k in ("a_tm", "a_bm", "a_lm", "a_rm"):
            cols[k].append(np.nan if a is None else m)
    return {k: np.asarray(v, dtype=np.float64) for k, v in cols.items()}


def test_frame_deviations_count_measurable_edges_only() -> None:
    ref = (22, 1057, 0, 1919)
    areas = [ref, (25, 1060, 0, 1919),  # 3 lines low: top inwards, bottom outwards
             (0, 1079, 0, 1919),  # full frame: picture in the bands
             (300, 700, 400, 1500),  # credits on black: smaller on every side
             (24, 1057, 0, 1919),  # dark sky only: top inwards, bottom in place
             None,  # black frame
             (22, 1057, 8, 1919),  # 8 pixels right: left inwards, right at the edge of the frame
             (23, 1057, 0, 1919)]  # one line: within the tolerance
    dev = lb.frame_deviations(_edge_columns(areas), ref, 152)
    assert dev.tolist() == [0, 3, 22, 0, 2, 0, 8, 1]
    dark = _edge_columns(areas, [500, 500, 500, 500, 90, 500, 500, 500])
    assert lb.frame_deviations(dark, ref, 152).tolist()[4] == 0  # a dark edge is not measurable
    night = _edge_columns([(24, 1056, 0, 1919)])  # sky and ground both lost: smaller on both sides
    assert lb.frame_deviations(night, ref, 152).tolist() == [0]
    # Ringing of a flash into the band: an outer row just above the black threshold is not measurable.
    assert lb.frame_deviations(_edge_columns([(21, 1057, 0, 1919)], 69.0), ref, 152).tolist() == [0]


def test_a_moved_shot_counts_from_its_first_frame() -> None:
    """PINACOLADA (31/10/2026): a shot 118 lines low whose top row stays dark for its first 4 s, then its
    bottom row turns dark now and then. Same four edges on every frame: one framing, one run from its first
    frame. A dark scene where no frame counts stays at 0."""
    ref, moved = (202, 1353, 0, 2047), (320, 1353, 0, 2047)
    areas = [ref] * 2 + [moved] * 8 + [ref] * 2
    tm = [500, 500, 100, 100, 100, 500, 500, 500, 500, 500, 500, 500]  # top row dark on the first 3 moved frames
    bm = [500] * 7 + [100, 100] + [500] * 3  # bottom row dark on 2 of them: the inward top does not count there
    cols = _edge_columns(areas)
    cols["a_tm"], cols["a_bm"] = np.asarray(tm, dtype=np.float64), np.asarray(bm, dtype=np.float64)
    assert lb.frame_deviations(cols, ref, 152).tolist() == [0, 0] + [118] * 8 + [0, 0]
    night = _edge_columns([ref] + [(24 + 180, 1353, 0, 2047)] * 5, [500] + [100] * 5)
    assert lb.frame_deviations(night, ref, 152).tolist() == [0] * 6


def test_deviation_runs_need_consecutive_frames() -> None:
    dev = np.array([0, 3, 3, 0, 3, 3, 3, 3, 0, 1, 1, 1, 1, 1, 0, 3, 1, 3, 1, 3, 1])
    assert lb.deviation_runs(dev, 0, 2, 3) == [(4, 7, True), (9, 13, False), (15, 20, False)]
    assert lb.deviation_runs(dev, 1, 2, 3) == [(4, 7, True)]  # house tolerance 1: one line is not reported


@pytest.mark.parametrize(("h", "w", "box"), [
    (1556, 2048, (0, 1555, 0, 2047)),  # 2K full aperture
    (2160, 3840, (276, 1883, 0, 3839)),  # UHD 2.39
    (1080, 1920, (0, 1079, 240, 1679)),  # 1.33 pillarbox: vertical bands
    (576, 720, (72, 503, 0, 719)),  # SD letterbox
])
def test_edges_any_resolution(h, w, box) -> None:
    from pad_guard.measure.video import edges

    y = np.full((h, w), 64, np.uint16)
    t, b, lf, r = box
    y[t: b + 1, lf: r + 1] = 600
    if t:
        y[t - 1, :] = np.where(np.arange(w) % 8 == 0, 90, 64)  # ringing into the band: not active
    e = edges(y.sum(axis=1, dtype=np.uint32), y.sum(axis=0, dtype=np.uint32), 68, 1)
    assert (e["a_t"], e["a_b"], e["a_l"], e["a_r"]) == box
    assert e["a_tm"] == round((600 * (r - lf + 1) + 64 * (w - (r - lf + 1))) / w, 1)
    area = lb.active_area(y, 0, 68)
    assert (area.top, area.bottom, area.left, area.right) == box  # the samples: the same criterion
