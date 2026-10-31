"""Non-regression of the real Arte master: its events against the reference kept in the repository.

The master (120 GB, not versioned) is analysed outside the repository; only the reference is versioned:
tests/golden/arte_master/reference.json, the events (type, severity, timecodes, texts) and the verdict.

    uv run python tools/recette/non_regression.py compare <out dir>    # differences, exit 1 if any
    uv run python tools/recette/non_regression.py write <out dir>      # new reference (after a decision)

A rerun from the measurements takes seconds:
    uv run pad-guard rerun <out dir> --from structure --profile profiles/arte_hd_sdr.yaml --no-thumbnails
(without --profile, rerun keeps the profile frozen in the out dir). With PAD_GUARD_ARTE_OUT=<out dir>,
pytest compares it too (tests/test_non_regression_arte.py).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REFERENCE = Path(__file__).resolve().parents[2] / "tests" / "golden" / "arte_master" / "reference.json"
FIELDS = ("type", "severity", "severity_source", "tc_start", "tc_end", "title", "value_text", "threshold_text",
          "occurrences")


def summary(out: Path) -> dict:
    """What the reference keeps of an analysis: the events and the verdict, nothing that depends on the run."""
    events = json.loads((out / "events.json").read_text(encoding="utf-8"))["events"]
    verdict = json.loads((out / "verdict.json").read_text(encoding="utf-8"))
    m = json.loads((out / "measurements.json").read_text(encoding="utf-8"))
    return {
        "source": {"name": Path(m["source"]["path"]).name, "sha256": m["source"]["sha256"]},
        "verdict": {"status": verdict["status"], "score": verdict["score"]},
        "events": [{k: e.get(k) for k in FIELDS} for e in events],
    }


def compare(current: dict, reference: dict) -> list[str]:
    """Differences, in French (empty: identical)."""
    out = []
    if current["source"]["sha256"] != reference["source"]["sha256"]:
        out.append(f"fichier différent : {current['source']['name']} au lieu de {reference['source']['name']}")
    if current["verdict"] != reference["verdict"]:
        out.append(f"verdict {current['verdict']} au lieu de {reference['verdict']}")
    key = lambda e: json.dumps(e, ensure_ascii=False, sort_keys=True)  # noqa: E731
    now, ref = {key(e) for e in current["events"]}, {key(e) for e in reference["events"]}
    out += [f"nouvel événement : {e['severity']} {e['type']} {e['tc_start']}-{e['tc_end']} {e['value_text']}"
            for e in current["events"] if key(e) not in ref]
    out += [f"événement disparu : {e['severity']} {e['type']} {e['tc_start']}-{e['tc_end']} {e['value_text']}"
            for e in reference["events"] if key(e) not in now]
    if len(current["events"]) != len(reference["events"]):
        out.append(f"{len(current['events'])} événements au lieu de {len(reference['events'])}")
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] not in ("compare", "write"):
        print(__doc__)
        return 2
    current = summary(Path(argv[1]))
    if argv[0] == "write":
        REFERENCE.parent.mkdir(parents=True, exist_ok=True)
        REFERENCE.write_text(json.dumps(current, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        print(f"Référence écrite : {len(current['events'])} événements, {current['verdict']['status']}")
        return 0
    diff = compare(current, json.loads(REFERENCE.read_text(encoding="utf-8")))
    print("\n".join(diff) if diff else f"Identique à la référence : {len(current['events'])} événements.")
    return 1 if diff else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
