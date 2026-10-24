"""Acceptance table of a draft profile against a reference profile (Phase 4b, SPEC §13).

For every value the reference profile fixes itself (not inherited from a norm), the status of
the draft: found identical, found different and not flagged (the failure the acceptance test
forbids), in conflict, rejected, reference to a norm, not found. Then the values the draft keeps
on fields the reference does not fix, and, for every wrong proposal of the model, the check that
stopped it. Markdown on standard output.

    uv run python tools/recette/recette.py profiles/drafts/arte_hd_sdr.findings.json profiles/arte_hd_sdr.yaml
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from pad_guard.draft import vocabulary
from pad_guard.draft.extract import canonical
from pad_guard.draft.schema import catalogue
from pad_guard.profiles.resolve import leaves, merge_layers

KEPT = ("A_VERIFIER", "INVRAISEMBLABLE")
NOT_FLAGGED = "TROUVÉE DIFFÉRENTE NON SIGNALÉE"


def same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return float(a) == float(b)
    return canonical(a) == canonical(b)


def short(value, limit: int = 60) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def reference_values(path: Path) -> dict:
    """Values the reference profile writes itself."""
    m = merge_layers(path)
    own = m.profile_file
    return {p: v for p, v in leaves({k: v for k, v in m.values.items() if k not in ("meta", "sources")})
            if m.origins.get(p) and m.origins[p].file == own}


def field_result(f: dict | None, want) -> str:
    if f is None:
        return "non trouvée"
    status = f["status"]
    if status == "A_VERIFIER":
        return "trouvée identique" if same(f["value"], want) else NOT_FLAGGED
    if status == "INVRAISEMBLABLE":
        return "identique, signalée INVRAISEMBLABLE" if same(f["value"], want) else "différente, signalée INVRAISEMBLABLE"
    if status == "CONFLIT":
        good = any(same(x["value"], want) for x in f["findings"] if x["status"] in (*KEPT, "CONFLIT"))
        return "CONFLIT (bonne valeur parmi les candidats)" if good else "CONFLIT (bonne valeur absente)"
    if status == "RENVOI_NORME":
        return "renvoi à une norme (sans valeur)"
    return f"rejetée ({status}, null)"


def stopped_by(x: dict, field_status: str) -> str:
    """The check that stopped one wrong proposal."""
    r = x.get("reason", "")
    if x["status"] == "A_VERIFIER":
        return "aucun contrôle, mais champ en CONFLIT" if field_status == "CONFLIT" else "NON ATTRAPÉE"
    if x["status"] == "INVRAISEMBLABLE":
        return "glossaire : unité" if "unité citée" in r else "glossaire : plage ou forme"
    if x["status"] == "CONFLIT":
        return "même citation pour deux champs (CONFLIT)"
    if "sans rapport" in r:
        return "vocabulaire du champ"
    if "ne contient pas le nombre" in r or "unité attendue" in r or "timecode" in r:
        return "nombre ou unité absent de la citation"
    if "ne contient pas le texte" in r:
        return "texte libre absent de la citation"
    if "ne dit pas" in r or "contredit" in r:
        return "sens du choix (négation, terme contraire)"
    if "introuvable" in r or "absente du lot" in r or "trop longue" in r:
        return "citation introuvable"
    if "programmes" in r or "colonne" in r:
        return "contexte programme long / court"
    if x["status"] == "VALEUR_INVALIDE":
        return "type du champ"
    if x["status"] == "CITATION_NON_VERIFIABLE":
        return "page sans texte"
    return f"autre ({x['status']} : {r[:50]})"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("findings", type=Path, help="profiles/drafts/<nom>.findings.json")
    parser.add_argument("reference", type=Path, help="profil de référence, ex. profiles/arte_hd_sdr.yaml")
    args = parser.parse_args()

    data = json.loads(args.findings.read_text(encoding="utf-8"))
    ref = reference_values(args.reference)
    fields = {f["path"]: f for f in data["fields"]}
    paths = [s.path for s in catalogue() if s.path not in vocabulary.INTERNAL and s.path in ref]

    print(f"# Recette : {args.findings.name} contre {args.reference.name}\n")
    print(f"Modèle {data['model']}, consigne {data['prompt_version']}, {data['pages']} pages, {data['batches']} lots.\n")
    print(f"## Valeurs fixées par {args.reference.name} ({len(paths)})\n")
    print("| Champ | Résultat | Référence | Brouillon |\n|---|---|---|---|")
    kinds: Counter = Counter()
    for p in paths:
        f = fields.get(p)
        kind = field_result(f, ref[p])
        kinds[kind] += 1
        print(f"| {p} | {kind} | {short(ref[p])} | {short(f['value']) if f else '—'} |")
    print("\n## Totaux\n")
    for kind, n in kinds.most_common():
        print(f"- {kind} : {n}")

    extra = [(p, f) for p, f in fields.items() if p not in ref and f["status"] in KEPT]
    print(f"\n## Valeurs retenues sur des champs que {args.reference.name} ne fixe pas ({len(extra)})\n")
    for p, f in extra:
        x = next(x for x in f["findings"] if x["status"] == f["status"])
        print(f"- {p} = {short(f['value'])} [{f['status']}] (p. {x['page']}) « {x['quote'][:110]} »")

    caught: Counter = Counter()
    for p, f in fields.items():
        if p not in ref:
            continue
        for x in f["findings"]:
            if x.get("source_type") != "client_refers_to_norm" and not same(x["value"], ref[p]):
                caught[stopped_by(x, f["status"])] += 1
    print("\n## Propositions fausses (valeur différente de la référence) : contrôle qui les arrête\n")
    for how, n in caught.most_common():
        print(f"- {how} : {n}")

    cited = [f"{n['norm']} (p. {n['page']}{'' if n['available'] else ', absente de normes/'})"
             for n in data.get("cited_norms", [])]
    print(f"\nNormes citées : {', '.join(cited) or 'aucune'}")
    print(f"meta.extends proposé : {', '.join(data['meta']['extends'])}")
    print(f"\nCritère (aucune valeur fausse non signalée) : {'ÉCHEC' if kinds[NOT_FLAGGED] else 'rempli'}")
    return 1 if kinds[NOT_FLAGGED] else 0


if __name__ == "__main__":
    raise SystemExit(main())
