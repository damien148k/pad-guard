"""``python -m pad_guard``: the same CLI as ``pad-guard`` (used by the local interface to run it)."""

from pad_guard.cli import app

if __name__ == "__main__":
    app(prog_name="pad-guard")
