"""Test bench: several local models on the same broadcaster PDFs, with a frozen prompt and glossary.

Three steps, all in one folder (default recette/banc/, not versioned):

    figer    copies the system prompt, normes/glossaire.yaml and the validated profiles (examples) into
             <folder>/gel/ and writes gel/manifest.json: their SHA-256, the PDFs and their SHA-256, the
             context size of each PDF (computed once, the same for every model), repeat_penalty, the
             git commit. Nothing changes afterwards: editing the glossary does not touch the bench.
    lancer   runs draft-profile with each model on each PDF from the frozen files, checks that every
             answer was asked with the frozen prompt and glossary, frees each model when done
             (keep_alive 0) and writes <folder>/<model>/<name>.* and resultats.json.
    comparer writes <folder>/comparaison.md: time, batches asked again page by page, pages at the
             limit, statuses and acceptance table against the reference profile, model by model; and
             whether the requests were the same for every model (prompt_sha256 of the first pass).

    uv run python tools/recette/banc.py figer --doc "arte_hd_sdr|diffuseurs/<document>.pdf|ARTE G.E.I.E.|profiles/arte_hd_sdr.yaml"
    uv run python tools/recette/banc.py lancer --modeles qwen3-vl:8b-instruct qwen3-vl:30b-a3b-instruct qwen3-vl:32b-instruct
    uv run python tools/recette/banc.py comparer
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import yaml

from pad_guard.draft import ROOT, DraftError, examples, glossary, make_draft, pdf, vocabulary
from pad_guard.draft.extract import PROMPT_FILE, PROMPT_VERSION, Context, batches, build_prompt, needed_context
from pad_guard.draft.schema import MAX_FINDINGS, catalogue
from pad_guard.llm import REPEAT_PENALTY, LLMError, OllamaClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
from recette import NOT_FLAGGED, field_result, reference_values  # noqa: E402

DEFAULT_FOLDER = ROOT / "recette" / "banc"
DEFAULT_MODELS = ["qwen3-vl:8b-instruct", "qwen3-vl:30b-a3b-instruct", "qwen3-vl:32b-instruct"]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def safe(model: str) -> str:
    return re.sub(r"[^\w.-]", "_", model)


def git_commit() -> str:
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True)
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return "inconnu"
    return head.stdout.strip() + (" (modifications non commitées)" if dirty.stdout.strip() else "")


def figer(args) -> int:
    gel = args.dossier / "gel"
    if gel.exists():
        if not args.remplacer:
            print(f"{gel} existe déjà : --remplacer pour refaire le gel (les résultats déjà obtenus ne seront plus comparables)")
            return 2
        shutil.rmtree(gel)
    (gel / "profiles").mkdir(parents=True)
    prompt = gel / PROMPT_FILE.name
    shutil.copyfile(PROMPT_FILE, prompt)
    shutil.copyfile(glossary.GLOSSARY, gel / glossary.GLOSSARY.name)
    profiles = {}
    for path in sorted((ROOT / "profiles").glob("*.yaml")):
        meta = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("meta") or {}
        if meta.get("status") == "validated":
            shutil.copyfile(path, gel / "profiles" / path.name)
            profiles[path.name] = sha256(path)
    system = prompt.read_text(encoding="utf-8")
    terms = glossary.load(gel / glossary.GLOSSARY.name)
    docs = []
    for spec in args.doc:
        try:
            name, pdf_path, broadcaster, reference = spec.split("|")
        except ValueError:
            print(f"--doc « {spec} » : attendu « nom|chemin.pdf|diffuseur|profil_de_reference.yaml »")
            return 2
        doc = pdf.read(Path(pdf_path))
        target = examples.Target(name, broadcaster, doc.sha256, Path(pdf_path).name)
        context = Context(glossary=terms, examples=examples.collect(gel / "profiles", target))
        plan = batches(doc)
        prompts = [build_prompt(doc, pages, catalogue(), context) for pages in plan]
        num_ctx, biggest, pages = needed_context(doc, plan, prompts, system)
        docs.append({"name": name, "pdf": pdf_path, "pdf_sha256": doc.sha256, "broadcaster": broadcaster,
                     "reference": reference, "reference_sha256": sha256(Path(reference)),
                     "num_ctx": args.num_ctx or num_ctx, "largest_request_estimate": biggest, "largest_pages": pages})
    manifest = {"prompt_version": PROMPT_VERSION, "prompt_file": prompt.name, "system_sha256": text_sha256(system),
                "glossary_sha256": terms.sha256, "profiles": profiles, "documents": docs,
                "repeat_penalty": args.repeat_penalty, "max_findings": MAX_FINDINGS, "git_commit": git_commit()}
    (gel / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Gel écrit dans {gel} : consigne {PROMPT_VERSION} ({manifest['system_sha256'][:12]}), glossaire "
          f"{terms.sha256[:12]}, {len(profiles)} profil(s) validé(s) pour les exemples, repeat_penalty "
          f"{args.repeat_penalty}")
    for d in docs:
        print(f"  {d['name']} : contexte {d['num_ctx']} jetons (plus grosse demande estimée {d['largest_request_estimate']}, "
              f"pages {d['largest_pages']})")
    return 0


def load_manifest(folder: Path) -> dict:
    gel = folder / "gel"
    manifest = json.loads((gel / "manifest.json").read_text(encoding="utf-8"))
    problems = []
    if text_sha256((gel / manifest["prompt_file"]).read_text(encoding="utf-8")) != manifest["system_sha256"]:
        problems.append("la consigne gelée a été modifiée")
    if glossary.load(gel / glossary.GLOSSARY.name).sha256 != manifest["glossary_sha256"]:
        problems.append("le glossaire gelé a été modifié")
    for name, digest in manifest["profiles"].items():
        if sha256(gel / "profiles" / name) != digest:
            problems.append(f"le profil gelé {name} a été modifié")
    for d in manifest["documents"]:
        if not Path(d["pdf"]).is_file() or pdf.sha256(Path(d["pdf"])) != d["pdf_sha256"]:
            problems.append(f"PDF absent ou différent : {d['pdf']}")
    if problems:
        raise SystemExit("Gel inutilisable : " + " ; ".join(problems) + ". Refaire « figer --remplacer ».")
    return manifest


def lancer(args) -> int:
    manifest = load_manifest(args.dossier)
    gel = args.dossier / "gel"
    results_path = args.dossier / "resultats.json"
    results = json.loads(results_path.read_text(encoding="utf-8")) if results_path.is_file() else {}
    try:
        installed = OllamaClient().installed()
    except LLMError as exc:
        print(exc)
        return 2
    for model in args.modeles:
        if model not in installed:
            print(f"{model} absent d'Ollama : « ollama pull {model} » (ignoré)")
            continue
        out = args.dossier / safe(model)
        for d in manifest["documents"]:
            if args.docs and d["name"] not in args.docs:
                continue
            client = OllamaClient(model=model, num_ctx=d["num_ctx"], repeat_penalty=manifest["repeat_penalty"])
            print(f"{model} / {d['name']} : contexte {d['num_ctx']} …", flush=True)
            start = time.perf_counter()
            entry = {"model": model, "document": d["name"]}
            try:
                x, files = make_draft(Path(d["pdf"]), d["name"], client, out, d["broadcaster"],
                                      glossary_path=gel / glossary.GLOSSARY.name, profiles_dir=gel / "profiles",
                                      system_path=gel / manifest["prompt_file"])
            except DraftError as exc:
                entry |= {"seconds": round(time.perf_counter() - start), "error": str(exc)}
                print(f"  échec : {exc}")
            else:
                log = [json.loads(line) for line in files["log"].read_text(encoding="utf-8").splitlines()]
                frozen = all(e["system_sha256"] == manifest["system_sha256"]
                             and e["glossary_sha256"] == manifest["glossary_sha256"] for e in log)
                entry |= {"seconds": round(time.perf_counter() - start), "batches": x.batches,
                          "requests": len(log), "retried_batches": sorted({e["batch"] for e in log
                                                                            if e["retry_page_by_page"]}),
                          "capped_pages": x.capped_pages, "frozen_inputs": frozen,
                          "output_tokens": sum(e["output_tokens"] or 0 for e in log),
                          "statuses": dict(Counter(r.status for r in x.fields)), "not_found": len(x.not_found)}
                print(f"  {entry['seconds']} s, {len(log)} requêtes, pages à la limite : {x.capped_pages or 'aucune'}"
                      + ("" if frozen else " ; ATTENTION : entrées non gelées"))
            results[f"{model}|{d['name']}"] = entry
            results_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        OllamaClient(model=model).release()  # keep_alive 0 before the next model
    return 0


def comparer(args) -> int:
    manifest = load_manifest(args.dossier)
    results = json.loads((args.dossier / "resultats.json").read_text(encoding="utf-8"))
    lines = ["# Banc de comparaison draft-profile", "",
             f"Consigne {manifest['prompt_version']} (SHA-256 {manifest['system_sha256'][:12]}), glossaire "
             f"{manifest['glossary_sha256'][:12]}, repeat_penalty {manifest['repeat_penalty']}, au plus "
             f"{manifest['max_findings']} propositions par réponse, commit {manifest['git_commit']}.", ""]
    for d in manifest["documents"]:
        ref = reference_values(Path(d["reference"]))
        extractable = {s.path for s in catalogue()} - vocabulary.INTERNAL
        lines += [f"## {d['name']} (contexte {d['num_ctx']} jetons ; référence {d['reference']})", "",
                  "| Modèle | Temps | Requêtes | Lots relancés | Pages à la limite | Identiques | **Non signalées** "
                  "| Conflits | Rejetées | Non trouvées | Jetons produits |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
        prints = {}
        for key, entry in results.items():
            if entry["document"] != d["name"]:
                continue
            model = entry["model"]
            if "error" in entry:
                lines.append(f"| {model} | {entry['seconds']} s | échec : {entry['error'][:80]} |||||||||")
                continue
            folder = args.dossier / safe(model)
            data = json.loads((folder / f"{d['name']}.findings.json").read_text(encoding="utf-8"))
            log = [json.loads(line) for line in (folder / f"{d['name']}.llm.jsonl").read_text(encoding="utf-8").splitlines()]
            prints[model] = [e["prompt_sha256"] for e in log if not e["retry_page_by_page"]]
            fields = {f["path"]: f for f in data["fields"]}
            kinds = Counter(field_result(fields.get(p), v) for p, v in ref.items() if p in extractable)
            conflicts = sum(n for k, n in kinds.items() if k.startswith("CONFLIT"))
            rejected = sum(n for k, n in kinds.items() if k.startswith("rejetée"))
            lines.append(f"| {model} | {entry['seconds']} s | {entry['requests']} | {len(entry['retried_batches'])} | "
                         f"{', '.join(map(str, entry['capped_pages'])) or '—'} | {kinds['trouvée identique']} | "
                         f"**{kinds[NOT_FLAGGED]}** | {conflicts} | {rejected} | {kinds['non trouvée']} | "
                         f"{entry['output_tokens']} |")
        same = len({tuple(p) for p in prints.values()}) <= 1
        lines += ["", f"Mêmes demandes pour tous les modèles (empreinte de chaque lot au premier passage) : "
                      f"{'oui' if same else 'NON'}.", ""]
    out = args.dossier / "comparaison.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(out.read_text(encoding="utf-8"))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dossier", type=Path, default=DEFAULT_FOLDER, help="dossier du banc (non versionné)")
    steps = parser.add_subparsers(dest="step", required=True)
    p = steps.add_parser("figer", help="geler consigne, glossaire, exemples et contexte")
    p.add_argument("--doc", action="append", required=True,
                   help="« nom|chemin.pdf|diffuseur|profil_de_reference.yaml » (répéter pour plusieurs PDF)")
    p.add_argument("--repeat-penalty", type=float, default=REPEAT_PENALTY)
    p.add_argument("--num-ctx", type=int, help="contexte imposé (défaut : calculé par PDF)")
    p.add_argument("--remplacer", action="store_true", help="refaire un gel existant")
    p = steps.add_parser("lancer", help="extraire avec chaque modèle")
    p.add_argument("--modeles", nargs="+", default=DEFAULT_MODELS)
    p.add_argument("--docs", nargs="+", help="seulement ces documents (noms du gel)")
    steps.add_parser("comparer", help="écrire comparaison.md")
    args = parser.parse_args()
    return {"figer": figer, "lancer": lancer, "comparer": comparer}[args.step](args)


if __name__ == "__main__":
    raise SystemExit(main())
