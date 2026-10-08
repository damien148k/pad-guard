# pad-checker

Outil de contrôle qualité automatisé de fichiers Prêt à Diffuser (PAD) pour **Lumiris Production** (restauration d'images). Il analyse un master **ProRes 422 HQ** ou **DNxHR HQX**, mesure les niveaux vidéo et audio, vérifie la structure du fichier (mire, noirs, timecode), compare le tout au profil de la chaîne cliente et produit un rapport.

Utilisateur final : **Vincent**, responsable technique. Il n'est pas développeur. Il veut déposer un fichier, choisir une chaîne et lire un rapport clair.

La spécification complète est dans `docs/SPEC.md`. La feuille de route et les critères d'acceptation sont dans `docs/ROADMAP.md`. Lis les deux avant de coder.

## Principes non négociables

1. **Verdict déterministe.** Le statut CONFORME / NON-CONFORME, le score et la gravité de chaque anomalie sont calculés par des règles. L'IA ne touche jamais au verdict ; elle rédige la synthèse et propose des qualifications que l'humain valide.
2. **Tout seuil vient du profil YAML** (`profiles/*.yaml`). Aucune valeur de norme n'est codée en dur. Si une valeur manque dans le profil, l'outil refuse de tourner avec un message clair. Le profil de référence est `profiles/arte_hd_sdr.yaml` : chaque valeur y cite le paragraphe des consignes Arte V2 ; les chaînes diffèrent sur des points importants (Arte : pas d'amorce, true peak -1 dBTP ; usage CST français : amorce, -3 dBTP), donc ne jamais supposer qu'une règle est universelle.
3. **Reproductibilité.** Même fichier + même profil + même version = même JSON de mesures, à l'octet près (pas d'échantillonnage aléatoire, pas de timestamps dans les données de mesure).
4. **Toutes les images sont analysées.** Pas d'échantillonnage par défaut. Un mode `--quick` peut exister pour un aperçu, mais il n'émet jamais de verdict.
5. **Confidentialité.** Rien ne sort de la machine, jamais. La couche IA tourne en local via Ollama ; aucun connecteur vers une API externe ne doit être ajouté.
6. **Les images sont la vérité.** Toute anomalie signalée dans le rapport doit être vérifiable : timecode exact, numéro d'image, valeur mesurée, seuil appliqué, et si possible une vignette.

## Stack

- Python 3.11+, gestion des dépendances avec `uv` (ou `pip` + `pyproject.toml`).
- FFmpeg 6+ et `ffprobe` dans le PATH (décodage ProRes/DNxHR sur CPU ; NVDEC ne gère pas ces codecs).
- `PyAV` pour décoder image par image, `NumPy` pour les calculs de pixels. Torch/CuPy sur GPU seulement si le profilage montre que NumPy est trop lent.
- `pydantic` pour les modèles de données (profil, mesures, événements, rapport).
- `typer` pour la CLI, `rich` pour l'affichage.
- `jinja2` pour le rapport Markdown, `weasyprint` (ou `markdown-pdf`) pour le PDF.
- Tests avec `pytest`. Fixtures vidéo générées par `tests/fixtures/make_fixtures.sh` (FFmpeg `testsrc2`, `smptehdbars`, `color`, `sine`).
- Couche IA : **Ollama uniquement** (bibliothèque Python `ollama`), modèle par défaut `qwen3-vl:32b-instruct`, repli `qwen3-vl:8b-instruct`, derrière une interface `LLMClient` (pour pouvoir brancher un autre moteur local plus tard). Pas d'API externe. Désactivée par défaut.

## Architecture (dossier `src/pad_checker/`)

```
probe/        lecture des métadonnées (ffprobe) et de l'en-tête du conteneur
decode/       décodage image par image (PyAV) et audio
measure/      mesures par image et par bloc audio -> measurements.json
structure/    mire, noirs de tête/queue, timecode, images figées, PSE
rules/        chargement du profil, application des règles -> events.json + verdict
report/       génération Markdown / PDF
llm/          synthèse rédigée et qualification suggérée (optionnel)
cli.py        point d'entrée `pad-checker`
```

Le flux est strictement linéaire : `probe -> decode+measure -> structure -> rules -> report`, avec un fichier JSON écrit entre chaque étape dans le dossier de travail. Chaque étape doit pouvoir être relancée seule à partir du JSON précédent.

## Conventions

- Code et commentaires en anglais, messages utilisateur et rapport en français.
- Timecodes toujours au format `HH:MM:SS:FF` (25 i/s) ; en interne, stocker aussi le numéro d'image absolu.
- Niveaux vidéo exprimés en valeurs de code **10 bits** dans le JSON, et en pourcentage dans le rapport. Pour un fichier 8 bits (ne devrait pas arriver avec ces codecs), convertir en 10 bits avant toute comparaison.
- Un événement = une plage continue d'images (`frame_start`, `frame_end`) partageant la même anomalie. Jamais une ligne par image dans le rapport.
- Gravité : `blocking` (fait échouer le PAD), `major` (à corriger, verdict NON-CONFORME), `minor` (toléré, signalé), `info`.
- Les tests ne dépendent d'aucun fichier externe au dépôt.

## Commandes

```bash
uv sync                                     # installer
uv run pad-checker analyze film.mov --profile profiles/france_tv_hd.yaml --out ./out/
uv run pad-checker rerun ./out/ [--from structure|rules|report] [--profile p.yaml]   # relancer sans refaire les mesures
uv run pad-checker report ./out/            # régénérer le rapport sans refaire les mesures
uv run pytest
```

## Décisions actées (7 octobre 2026)

- **Pistes audio** : une piste du profil = un canal, numéroté à partir de 1 dans l'ordre de tous les flux audio du conteneur (stéréo ou mono, peu importe). `probe.json` enregistre la correspondance (flux, canal) → numéro de piste.
- **Niveaux Y** : `y_below_pct` / `y_above_pct` se mesurent par rapport aux bornes **tolérées** du profil (55/967 en 10 bits pour -1 %/103 %), arrondies vers l'extérieur et inclusives. `y_below_legal_pct` / `y_above_legal_pct` (64/940) sont de l'information, sans règle.
- **`null` dans un profil** : jamais de désactivation implicite. Une règle qui dépend d'un champ `null` fait refuser l'analyse.
- **Arte, mode `leaders: none`** : mire → `structure_bars_present` (`blocking`) ; noir de tête > `head_max_seconds` ou de queue > `tail_max_seconds` → `structure_black_too_long` (`minor`).
- **Intégrité** : vérifiée pendant la passe de décodage/mesure (erreurs PyAV collectées, images décodées = `nb_frames`), jamais par un second décodage.
- **Profils** : schéma commun (`format.fps_allowed`, `audio.loudness.long/short`, `structure.leaders`). Les tests des fixtures à amorce classique utilisent `tests/profiles/test_classic.yaml`, pas un profil de chaîne.

## Ce qu'il ne faut pas faire

- Ne pas invoquer FFmpeg via `os.system` avec des chaînes concaténées : utiliser `subprocess.run` avec une liste d'arguments.
- Ne pas charger tout le film en mémoire : traiter image par image ou par lots de N images.
- Ne pas ajouter de dépendance lourde (Torch, OpenCV) sans justification chiffrée.
- Ne pas inventer de valeurs de norme. En cas de doute sur une valeur, la laisser à `null` dans le profil et le signaler.
