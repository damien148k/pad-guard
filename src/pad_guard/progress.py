"""--progress-json: the progress of a command as JSON Lines, read by the local interface (Phase 5).

One line per event: ``{"t": seconds since the start, "stage": ..., ...}``. Stages of ``analyze``:
probe, measure_video (with ``done`` / ``total`` frames), measure_audio, structure, rules, report,
done; ``log`` carries the messages the CLI prints with --verbose. ``draft-profile``: read,
extract (``done`` / ``total`` batches), done. Not a measurement file: it holds times.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

FRAME_INTERVAL = 0.5  # seconds between two measure_video lines


class ProgressFile:
    def __init__(self, path: Path | None):
        self.path = path
        self.start = time.monotonic()
        self.last_frames = -FRAME_INTERVAL
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")

    def emit(self, stage: str, msg: str = "", **extra: Any) -> None:
        if self.path is None:
            return
        line = {"t": round(time.monotonic() - self.start, 2), "stage": stage}
        if msg:
            line["msg"] = msg
        line.update(extra)
        with self.path.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    def counter(self, stage: str, done: int, total: int | None) -> None:
        """Throttled: at most one line every FRAME_INTERVAL seconds, and the last one."""
        now = time.monotonic() - self.start
        if done != total and now - self.last_frames < FRAME_INTERVAL:
            return
        self.last_frames = now
        self.emit(stage, done=done, total=total)

    def log(self, msg: str) -> None:
        self.emit("log", msg)
