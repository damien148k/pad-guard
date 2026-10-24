"""Annex charts of the report (SPEC §8, section 7): luma extremes and momentary loudness over time.

Long films are reduced to at most ``POINTS`` columns by keeping the extreme of each bucket
(min of y_p01, max of y_p99, max of momentary loudness), so a single bad frame stays visible.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

POINTS = 2000
_SAVE = dict(dpi=110, metadata={"Software": None})  # no tool version in the PNG: same input, same bytes


def _buckets(values: np.ndarray, reduce) -> tuple[np.ndarray, np.ndarray]:
    n = values.size
    if n <= POINTS:
        return np.arange(n, dtype=np.float64), values
    edges = np.linspace(0, n, POINTS + 1).astype(np.int64)
    with np.errstate(all="ignore"):
        out = reduce.reduceat(values, edges[:-1])
    return edges[:-1].astype(np.float64), out


def _minutes_axis(ax, total_seconds: float) -> None:
    ax.set_xlim(0, max(total_seconds / 60, 1e-6))
    ax.set_xlabel("minutes depuis le début du fichier")
    ax.grid(True, alpha=0.3)


def luma_chart(path: Path, y_p01: np.ndarray, y_p99: np.ndarray, fps: float, legal: tuple[int, int],
               tolerance: tuple[int, int]) -> None:
    x, hi = _buckets(y_p99, np.maximum)
    _, lo = _buckets(y_p01, np.minimum)
    fig, ax = plt.subplots(figsize=(9, 3.2))
    ax.fill_between(x / fps / 60, lo, hi, color="#4c78a8", alpha=0.35, linewidth=0, label="y_p01 – y_p99")
    ax.plot(x / fps / 60, hi, color="#4c78a8", linewidth=0.6)
    ax.plot(x / fps / 60, lo, color="#4c78a8", linewidth=0.6)
    for value, style, label in ((legal[0], ":", "légal"), (legal[1], ":", None),
                                (tolerance[0], "--", "toléré"), (tolerance[1], "--", None)):
        ax.axhline(value, color="#e45756", linestyle=style, linewidth=0.8, label=label)
    ax.set_ylim(0, 1023)
    ax.set_ylabel("Y (code 10 bits)")
    _minutes_axis(ax, y_p99.size / fps)
    ax.legend(loc="lower right", fontsize=7)
    fig.tight_layout()
    fig.savefig(path, **_SAVE)
    plt.close(fig)


def loudness_chart(path: Path, groups: dict[str, np.ndarray], block_seconds: float, target: float) -> None:
    fig, ax = plt.subplots(figsize=(9, 3.2))
    total = 0.0
    for name, m in groups.items():
        values = np.nan_to_num(m, nan=-70.0)
        x, y = _buckets(values, np.maximum)
        ax.plot(x * block_seconds / 60, y, linewidth=0.6, label=name)
        total = max(total, m.size * block_seconds)
    ax.axhline(target, color="#e45756", linestyle="--", linewidth=0.8, label="cible")
    ax.set_ylim(-70, 0)
    ax.set_ylabel("loudness momentané (LUFS)")
    _minutes_axis(ax, total)
    ax.legend(loc="lower right", fontsize=7)
    fig.tight_layout()
    fig.savefig(path, **_SAVE)
    plt.close(fig)
