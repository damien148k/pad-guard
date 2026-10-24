"""Programme range used for the global audio values (SPEC §5.3: head and tail excluded).

* ``structure.leaders: none`` or ``audio.exclude_head_tail: false``: the whole file.
* Otherwise the programme starts at ``structure.timecode.program_start``, located with the file
  timecode; if the file has no usable timecode, at the position the profile expects
  (``program_start - file_start``). It ends with the last frame that is not black
  (``y_p99 >= structure.black.y_max``), so that the tail black and silence are left out.

The structure step (Phase 3) checks the head and tail themselves; this range only decides which
samples count as programme for the loudness measurements, and it is recorded with its method.
"""

from __future__ import annotations

from collections.abc import Sequence
from fractions import Fraction

from pad_guard import timecode
from pad_guard.measure.models import ProgramRange
from pad_guard.probe.models import ProbeResult
from pad_guard.rules.profile import Profile


def frame_to_sample(frame: int, fps: Fraction, sample_rate: int) -> int:
    return round(frame * Fraction(sample_rate) / fps)


def program_range(
    probe: ProbeResult, profile: Profile, y_p99: Sequence[int], frames: int, sample_rate: int
) -> ProgramRange:
    fps = Fraction(probe.video.r_frame_rate)
    clock = timecode.Clock(fps, probe.timecode, probe.timecode_format)
    s = profile.structure
    start, start_method = 0, "file"
    end, end_method = frames - 1, "file"

    if s.leaders != "none" and profile.audio.exclude_head_tail:
        program = clock.absolute(s.timecode.program_start)
        offset = clock.frame(s.timecode.program_start) if clock.start_tc else None
        if offset is not None and 0 <= offset < frames:
            start, start_method = offset, "timecode"
        else:
            expected = program - clock.absolute(s.timecode.file_start)
            start, start_method = min(max(expected, 0), frames - 1), "profile"
        last = frames - 1
        while last > start and y_p99[last] < s.black.y_max:
            last -= 1
        if last < frames - 1:
            end, end_method = last, "black_tail"

    return ProgramRange(
        frame_start=start,
        frame_end=end,
        tc_start=clock.tc(start) if clock.start_tc else None,
        tc_end=clock.tc(end) if clock.start_tc else None,
        sample_start=frame_to_sample(start, fps, sample_rate),
        sample_end=frame_to_sample(end + 1, fps, sample_rate),
        start_method=start_method,
        end_method=end_method,
    )

