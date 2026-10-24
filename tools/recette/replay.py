"""Rebuild a draft from the raw model answers of its .llm.jsonl, without calling Ollama.

The checks of draft-profile are deterministic: replaying the same answers after a change of
the checks, the glossary or the writer shows its effect in seconds instead of a new extraction
(13 minutes for the 94 pages of Arte with qwen3-vl:8b). The draft and findings.json are rewritten;
the .llm.jsonl is kept as it was (it says what the model was really asked). When the requests
have changed since the extraction (glossary, prompt: other prompt_sha256), the replay is only
indicative, and says so.

    uv run python tools/recette/replay.py "diffuseurs/<document>.pdf" --name arte_hd_sdr --broadcaster "ARTE G.E.I.E."
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pad_guard.draft import DRAFTS, DraftError, make_draft
from pad_guard.llm import LLMClient, LLMError, LLMRequest


class Replay(LLMClient):
    """Answers each page batch with the recorded answer of the same batch."""

    def __init__(self, log: list[dict]):
        self.model = log[0]["model"]
        self.log = log
        self.batch = 0

    def generate(self, request: LLMRequest) -> str:
        if self.batch >= len(self.log):
            raise LLMError(f"le journal n'a que {len(self.log)} lot(s) : ce n'est pas le même PDF")
        answer = self.log[self.batch]["response"]
        self.batch += 1
        return answer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("pdf", type=Path, help="PDF du diffuseur (dans diffuseurs/)")
    parser.add_argument("--name", required=True, help="nom du brouillon, ex. arte_hd_sdr")
    parser.add_argument("--broadcaster", help="nom du diffuseur (exclut ses exemples)")
    parser.add_argument("--drafts", type=Path, default=DRAFTS, help="dossier des brouillons")
    args = parser.parse_args()

    log_path = args.drafts / f"{args.name}.llm.jsonl"
    original = log_path.read_text(encoding="utf-8")
    log = [json.loads(line) for line in original.splitlines() if line.strip()]
    if not log:
        print(f"{log_path} est vide")
        return 2
    client = Replay(log)
    try:
        x, files = make_draft(args.pdf, args.name, client, args.drafts, broadcaster=args.broadcaster)
    except DraftError as exc:
        print(f"Rejeu impossible : {exc}")
        return 2
    finally:
        replayed = log_path.read_text(encoding="utf-8")
        log_path.write_text(original, encoding="utf-8", newline="\n")  # the real requests, not the replay's
    now = [json.loads(line) for line in replayed.splitlines() if line.strip()]
    changed = [e["pages"] for e, n in zip(log, now) if e.get("prompt_sha256") != n.get("prompt_sha256")]
    if changed:
        print(f"Rejeu indicatif : {len(changed)} demande(s) ont changé depuis l'extraction (glossaire ou consigne), "
              f"pages {', '.join('-'.join(map(str, p)) for p in changed[:8])}{' …' if len(changed) > 8 else ''}")
    if client.batch != len(log):
        print(f"Attention : {len(log)} lot(s) dans le journal, {client.batch} rejoué(s).")
    counts: dict[str, int] = {}
    for r in x.fields:
        counts[r.status] = counts.get(r.status, 0) + 1
    print(f"{args.name} ({x.model}, {x.batches} lots) : " + ", ".join(f"{s} {n}" for s, n in sorted(counts.items()))
          + f", non trouvés {len(x.not_found)}")
    print(f"Normes citées : {', '.join(x.cited_norms()) or 'aucune'}")
    print(f"Brouillon : {files['yaml']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
