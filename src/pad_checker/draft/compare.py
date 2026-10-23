"""compare-profiles: two profiles merged over their norms, compared value by value (SPEC §13).

Works on drafts too (an incomplete profile is merged, not validated). When a profile has a
``<name>.findings.json`` next to it (a draft), the extraction status of each value is shown.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pad_checker.profiles.resolve import leaves, merge_layers

SAME, DIFFERENT, ONLY_A, ONLY_B = "identique", "différent", "seulement A", "seulement B"


@dataclass
class Row:
    path: str
    kind: str
    a: Any
    a_file: str | None
    b: Any
    b_file: str | None
    a_status: str | None = None  # draft extraction status (A_VERIFIER, CONFLIT...)
    b_status: str | None = None


def _equal(x: Any, y: Any) -> bool:
    return json.dumps(x, sort_keys=True) == json.dumps(y, sort_keys=True) or x == y


def statuses(path: Path) -> dict[str, str]:
    sidecar = path.with_name(path.stem + ".findings.json")
    if not sidecar.is_file():
        return {}
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    return {f["path"]: f["status"] for f in data["fields"]}


def compare(a: Path, b: Path) -> list[Row]:
    ma, mb = merge_layers(a), merge_layers(b)
    va = dict(leaves({k: v for k, v in ma.values.items() if k != "meta"}))
    vb = dict(leaves({k: v for k, v in mb.values.items() if k != "meta"}))
    sa, sb = statuses(a), statuses(b)
    rows = []
    for path in [*va, *(p for p in vb if p not in va)]:
        if path not in vb:
            kind = ONLY_A
        elif path not in va:
            kind = ONLY_B
        else:
            kind = SAME if _equal(va[path], vb[path]) else DIFFERENT
        oa, ob = ma.origins.get(path), mb.origins.get(path)
        rows.append(Row(path=path, kind=kind, a=va.get(path), a_file=oa.file if oa else None, b=vb.get(path),
                        b_file=ob.file if ob else None, a_status=sa.get(path), b_status=sb.get(path)))
    return rows
