from __future__ import annotations

import pytest
from typer.testing import CliRunner

from pad_checker import timecode
from pad_checker.cli import EXIT_NOT_IMPLEMENTED, app
from pad_checker.rules import expr


@pytest.mark.parametrize(
    ("tc", "frames"),
    [("00:00:00:00", 0), ("00:00:01:00", 25), ("09:59:50:00", 899_750), ("10:00:00:00", 900_000), ("10:00:02:24", 900_074)],
)
def test_timecode_roundtrip(tc: str, frames: int) -> None:
    assert timecode.to_frames(tc) == frames
    assert timecode.from_frames(frames) == tc


@pytest.mark.parametrize("tc", ["10:00:00", "10:00:00:25", "24:00:00:00", "10:60:00:00", "ab:00:00:00"])
def test_timecode_invalid(tc: str) -> None:
    with pytest.raises(ValueError):
        timecode.to_frames(tc)


def test_timecode_drop_frame() -> None:
    assert timecode.is_drop_frame("10:00:00;00")
    assert not timecode.is_drop_frame("10:00:00:00")
    with pytest.raises(ValueError):
        timecode.to_frames("10:00:00;00")


def test_expr_evaluate() -> None:
    env = {"worst_value": 1010, "area_pct_max": 2.0, "duration_frames": 10}
    assert expr.evaluate("worst_value > 1004 or area_pct_max > 5", env) is True
    assert expr.evaluate("area_pct_max >= 1 and duration_frames >= 25", env) is False
    assert expr.evaluate("1 <= area_pct_max < 3", env) is True
    assert expr.evaluate("100 - 40*blocking - 10*major - 2*minor", {"blocking": 1, "major": 2, "minor": 3}) == 34


@pytest.mark.parametrize(
    "bad",
    [
        "__import__('os')",
        "worst_value.__class__",
        "[x for x in ()]",
        "'abc' == 'abc'",
        "lambda: 1",
        "worst_value if True else 0",
        "True",
        "2 ** 1000000",
    ],
)
def test_expr_rejects(bad: str) -> None:
    with pytest.raises(expr.ExpressionError):
        expr.evaluate(bad, {"worst_value": 1})


@pytest.mark.parametrize(
    "args",
    [
        ["analyze", "x.mov", "--profile", "p.yaml", "--out", "out"],
        ["report", "out"],
    ],
)
def test_cli_stubs(args: list[str]) -> None:
    result = CliRunner().invoke(app, args)
    assert result.exit_code == EXIT_NOT_IMPLEMENTED
    assert "non implémenté" in result.output


def test_cli_version() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "pad-checker" in result.output
