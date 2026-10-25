# PAD Guard

Outil de contrôle qualité automatisé de fichiers Prêt à Diffuser (PAD) pour **Lumiris Production** (restauration d'images). Il analyse un master dans les formats professionnels courants (ProRes, DNxHD/DNxHR, XAVC/AVC-Intra, XDCAM HD422, H.264/HEVC, non compressé ; SD à 4K ; 23,976 à 60 i/s ; liste dans `src/pad_guard/formats.py`), mesure les niveaux vidéo et audio, vérifie la structure du fichier (mire, noirs, timecode), compare le tout au profil de la chaîne cliente et produit un rapport.

Utilisateur final : **Vincent**, responsable technique. Il n'est pas développeur. Il veut déposer un fichier, choisir une chaîne et lire un rapport clair.

La spécification complète est dans `docs/SPEC.md`. La feuille de route et les critères d'acceptation sont dans `docs/ROADMAP.md`. Lis les deux avant de coder.

## Principes non négociables

1. **Verdict déterministe.** Le statut CONFORME / NON-CONFORME, le score et la gravité de chaque anomalie sont calculés par des règles. L'IA ne touche jamais au verdict ; elle rédige la synthèse et propose des qualifications que l'humain valide.
2. **Le cahier des charges du client fait foi ; les normes informent et complètent** (décision de Damien, 23 octobre 2026). Tout seuil vient du profil effectif, résolu de façon déterministe à partir de `profiles/*.yaml` et des `normes/*.yaml` dont il hérite (priorité : profil diffuseur > `lumiris_maison` > normes internationales, dans l'ordre de `extends`). Le profil effectif est écrit dans `out/effective_profile.json` avec l'origine de chaque valeur.
   - Une valeur fixée par le client s'applique telle quelle, et figure dans le profil du client avec sa citation, même si une norme dit la même chose. Si une norme diffère, le rapport l'indique en information (« Arte : 103 % ; EBU R 103 : 105 % »), sans effet sur le verdict. Un écart avec une norme n'est jamais une raison de marquer A VERIFIER.
   - Renvoi explicite du client à une norme (décision de Damien, 24 octobre 2026) : quand le document du client renvoie à une norme (« conforme à EBU R 128 »), c'est une exigence du client pour les champs que cette norme fixe réellement : la valeur vient de la norme, avec la source « <Diffuseur> §x, par renvoi à <norme> », sans plafonnement. Le profil le déclare dans `meta.refers_to` (`norm`, citée dans `extends`, et `source`, la citation du renvoi) ; draft-profile ne fait que proposer le renvoi, un humain le confirme dans review-profile. Une valeur chiffrée par le client l'emporte toujours sur le renvoi.
   - Une valeur absente chez le client mais présente dans une norme à laquelle il ne renvoie pas s'applique comme recommandation (source NORME) : toute anomalie qui en dépend est plafonnée à `minor`, comme DEDUIT. Une norme seule ne rend jamais un PAD NON-CONFORME. Les règles maison (`lumiris_maison`) ne sont pas des normes : elles gardent leur gravité.
   - Méthode de mesure non précisée par le client (préfiltre, fenêtres, gating) : suivre la norme plutôt qu'un choix maison.
   - « A VERIFIER » veut dire uniquement : valeur sans citation du document du client. Aucune valeur de norme n'est codée en dur. Si une valeur manque dans le profil effectif, l'outil refuse de tourner avec un message clair. Le profil de référence est `profiles/arte_hd_sdr.yaml` : chaque valeur propre à Arte y cite le paragraphe des consignes Arte V2 ; chaque chaîne est décrite par son seul document : rien n'est supposé, aucune règle n'est universelle, aucun « usage » n'est prêté à une chaîne que son document ne dit pas.
3. **Reproductibilité.** Même fichier + même profil + même version = même JSON de mesures, à l'octet près (pas d'échantillonnage aléatoire, pas de timestamps dans les données de mesure).
4. **Toutes les images sont analysées.** Pas d'échantillonnage par défaut. Un mode `--quick` peut exister pour un aperçu, mais il n'émet jamais de verdict.
5. **Confidentialité.** Rien ne sort de la machine, jamais. La couche IA tourne en local via Ollama ; aucun connecteur vers une API externe ne doit être ajouté.
6. **Les images sont la vérité.** Toute anomalie signalée dans le rapport doit être vérifiable : timecode exact, numéro d'image, valeur mesurée, seuil appliqué, et si possible une vignette.
7. **Profil non validé.** Un profil en `meta.status: draft` peut être utilisé, mais le rapport porte en tête « PROFIL NON VALIDÉ — résultat indicatif » et n'affiche jamais CONFORME (il affiche « INDICATIF : sans anomalie bloquante » ou « INDICATIF : NON-CONFORME »). Les valeurs venant d'un PDF par IA sont toujours `A_VERIFIER` tant qu'un humain ne les a pas validées.

## Stack

- Python 3.11+, gestion des dépendances avec `uv` (ou `pip` + `pyproject.toml`).
- FFmpeg 6+ et `ffprobe` dans le PATH (décodage ProRes/DNxHR sur CPU ; NVDEC ne gère pas ces codecs).
- `PyAV` pour décoder image par image, `NumPy` pour les calculs de pixels. Torch/CuPy sur GPU seulement si le profilage montre que NumPy est trop lent.
- `pydantic` pour les modèles de données (profil, mesures, événements, rapport).
- `typer` pour la CLI, `rich` pour l'affichage.
- `jinja2` pour le rapport Markdown, `weasyprint` (ou `markdown-pdf`) pour le PDF.
- Tests avec `pytest`. Fixtures vidéo générées par `tests/fixtures/make_fixtures.sh` (FFmpeg `testsrc2`, `smptehdbars`, `color`, `sine`).
- Couche IA : **Ollama uniquement** (bibliothèque Python `ollama`), modèle par défaut `qwen3-vl:8b-instruct` pour `draft-profile` et la synthèse, CLI et interface, dans la seule constante `llm.DEFAULT_MODEL` (décision de Damien, 24 octobre 2026 : le 32B est trop lent sur la RTX 3080 Ti, il ne sert qu'en recette ponctuelle, par `--model` / `--llm-model` ou le choix du modèle dans l'interface), derrière une interface `LLMClient` (pour pouvoir brancher un autre moteur local plus tard). Pas d'API externe. Désactivée par défaut. Deux usages : la synthèse du rapport (Phase 4c) et l'extraction d'un profil brouillon depuis le PDF d'un diffuseur (`draft-profile`, Phase 4b), toujours en `A_VERIFIER`.
- Lecture des PDF (Phase 4b) : `pdfplumber` (texte) et `pypdfium2` (rendu des pages). Pas de PyMuPDF pour cet usage (licence AGPL).
- Interface locale (Phase 5) : `starlette` + `uvicorn` sur 127.0.0.1 seulement (pas FastAPI : il tire `opentelemetry-api`), page en Preact + htm copiés dans `ui/static/vendor/`, polices copiées dans `ui/static/fonts/` (OFL). Aucun CDN : la Content-Security-Policy l'interdit et un test le vérifie. Maquette de référence : `design/maquette/` (export Claude Design). Test de bout en bout avec Playwright (`-m e2e`, hors pytest par défaut).
- pymupdf (AGPL) est utilisé pour produire rapport.pdf : acceptable pour un usage interne Lumiris ; à remplacer avant toute distribution de PAD Guard.

## Architecture

```
profiles/             profils des diffuseurs (YAML) ; meta.extends cite les normes héritées
normes/               normes lisibles par l'outil (YAML partiels, une source par valeur)
normes/glossaire.yaml vocabulaire des diffuseurs pour draft-profile (termes, unités, plages vraisemblables) : pas une norme
normes/sources/       PDF des normes (non versionné, inventaire dans README.md)
diffuseurs/           PDF des cahiers des charges des diffuseurs (non versionné, inventaire dans README.md)
src/pad_guard/
  profiles/   résolution de l'héritage -> profil effectif, origine de chaque valeur, conflits
  probe/      lecture des métadonnées (ffprobe) et de l'en-tête du conteneur
  decode/     décodage image par image (PyAV) et audio
  measure/    mesures par image (dont le peignage) et par bloc audio -> measurements.json
  structure/  mire, noirs de tête/queue, timecode, images figées, PSE
  rules/      schéma du profil, application des règles -> events.json + verdict
  report/     génération Markdown / PDF ; ai.py : synthèse et qualifications IA, contrôlées, rejouées depuis llm_synthese.json
  llm/        LLMClient et OllamaClient (seule implémentation), consignes versionnées dans llm/prompts/
  draft/      draft-profile (lecture du PDF, schéma d'extraction, contrôle des citations), review-profile, compare-profiles
  ui/         `pad-guard ui` : serveur local, API sur les JSON et les fonctions de PAD Guard, tâches (la CLI en
              sous-processus, --progress-json), page dans static/ ; affiche, ne décide jamais
  cli.py      point d'entrée `pad-guard` (aussi `python -m pad_guard`)
```

Le flux est strictement linéaire : `profil effectif -> probe -> decode+measure -> structure -> rules -> report`, avec un fichier JSON écrit entre chaque étape dans le dossier de travail (`effective_profile.json`, `probe.json`, `measurements.json`…). Chaque étape doit pouvoir être relancée seule à partir du JSON précédent.

## Conventions

- Code et commentaires en anglais, messages utilisateur et rapport en français.
- Timecodes au format `HH:MM:SS:FF` ; en interne, stocker aussi le numéro d'image absolu.
- La cadence et le balayage du fichier d'entrée ne sont pas maîtrisés (ils dépendent du client) ; ils sont lus dans `probe.json` (`r_frame_rate`, `avg_frame_rate`, `field_order`) et confirmés par une détection de peignage pendant le décodage. Depuis la Phase 6, les cadences 23,976 à 60 i/s sont mesurées ; PAD Guard ne refuse que ce qu'il ne sait pas mesurer (`formats.py`), un écart avec le profil est une anomalie de format. Aucun 25 en dur dans le code : la cadence vient de `probe.json`, la base du timecode du fichier (`timecode_format`), les durées des règles sont en secondes.
- Niveaux vidéo exprimés en valeurs de code **10 bits** dans le JSON, et en pourcentage dans le rapport. Un fichier 8 bits est converti en 10 bits avant toute comparaison ; un fichier 12 bits est mesuré en 12 bits avec les seuils 10 bits x 4 ; plage pleine et R'G'B' sont convertis en plage légale avant la mesure.
- Un événement = une plage continue d'images (`frame_start`, `frame_end`) partageant la même anomalie. Jamais une ligne par image dans le rapport.
- Gravité : `blocking` (fait échouer le PAD), `major` (à corriger, verdict NON-CONFORME), `minor` (toléré, signalé), `info`.
- Les tests ne dépendent d'aucun fichier externe au dépôt.

## Format de livraison

Le profil décrit le format que le diffuseur attend en livraison (`format.delivery` : `scan` `progressive` | `interlaced_tff` | `interlaced_bff` | `psf`, cadences, codec de livraison). Quand le fichier analysé (le master Lumiris) diffère du format de livraison, le rapport l'indique dans une section « Livraison » avec un événement de gravité `info` nommé `delivery_conversion_required` (ex. « Master 25p détecté ; le diffuseur attend du 50i entrelacé : conversion requise »). Ce n'est pas une non-conformité du master. Les valeurs de `format.delivery` d'Arte doivent citer le paragraphe des consignes Arte ; sinon `null` et `A VERIFIER`.

## Commandes

Avant tout commit, lancer `uv run pytest` sans pipe ni tail, et ne committer que si le code de retour de pytest est 0.

```bash
uv sync                                     # installer
uv run pad-guard analyze film.mov --profile profiles/france_tv_hd.yaml --out ./out/
uv run pad-guard rerun ./out/ [--from structure|rules|report] [--profile p.yaml]   # relancer sans refaire les mesures
uv run pad-guard report ./out/            # régénérer le rapport sans refaire les mesures
uv run pad-guard report ./out/ --llm ollama [--llm-model qwen3-vl:8b-instruct] [--llm-refresh]   # synthèse IA locale (aussi sur analyze et rerun)
uv run pad-guard validate-profile profiles/arte_hd_sdr.yaml   # schéma, normes héritées, cycles
uv run pad-guard explain-profile profiles/arte_hd_sdr.yaml    # chaque valeur, son origine, les conflits
uv run pad-guard draft-profile diffuseurs/doc.pdf --name nom  # brouillon dans profiles/drafts/ (Ollama local)
uv run pad-guard review-profile profiles/drafts/nom.yaml      # relecture champ par champ -> profiles/nom.yaml validé
uv run pad-guard compare-profiles a.yaml b.yaml               # différences entre deux profils effectifs
uv run pad-guard ui                                           # interface locale (127.0.0.1:8765), voir docs/GUIDE_VINCENT.md
uv run pytest
uv run pytest -m e2e                                          # interface dans Chromium (playwright install chromium une fois)
```

## Décisions actées (7 octobre 2026)

- **Pistes audio** : une piste du profil = un canal, numéroté à partir de 1 dans l'ordre de tous les flux audio du conteneur (stéréo ou mono, peu importe). `probe.json` enregistre la correspondance (flux, canal) → numéro de piste.
- **Niveaux Y** : `y_below_pct` / `y_above_pct` se mesurent par rapport aux bornes **tolérées** du profil (55/967 en 10 bits pour -1 %/103 %), arrondies vers l'extérieur et inclusives. `y_below_legal_pct` / `y_above_legal_pct` (64/940) sont de l'information, sans règle.
- **`null` dans un profil** : jamais de désactivation implicite. Une règle qui dépend d'un champ `null` fait refuser l'analyse.
- **Arte, mode `leaders: none`** : mire → `structure_bars_present` (`blocking`) ; noir de tête > `head_max_seconds` ou de queue > `tail_max_seconds` → `structure_black_too_long` (`minor`).
- **Intégrité** : vérifiée pendant la passe de décodage/mesure (erreurs PyAV collectées, images décodées = `nb_frames`), jamais par un second décodage.
- **Profils** : schéma commun (`format.fps_allowed`, `audio.loudness.long/short`, `structure.leaders`). Les tests des fixtures à amorce classique utilisent `tests/profiles/test_classic.yaml`, pas un profil de chaîne.

## Interface locale (Phase 5)

- Aucune logique métier dans `ui/` ni dans le JavaScript : verdict, score, gravités, seuils, qualifications et textes viennent des JSON de PAD Guard (`rapport.json`, écrit par le rapport à partir des mêmes sections que `rapport.md`) ou des fonctions Python existantes (`probe_file`, `audio_map.parse`, `pipeline.preflight`, `draft.review`). Une donnée que PAD Guard ne produit pas ne s'affiche pas.
- Les films ne transitent jamais par le navigateur : la page ne reçoit que des chemins (boîte de dialogue native ouverte par le serveur, ou chemin collé).
- Une anomalie est désignée par `Event.key` (`type@frame_start@groupe`), jamais par son numéro, pour les liens et les vignettes.
- Les analyses et `draft-profile` lancés depuis l'interface exécutent la CLI (`python -m pad_guard … --progress-json`), une tâche à la fois.
- Avant chaque lancement qui utilise l'IA locale (brouillon, synthèse), la page affiche le modèle utilisé et propose les modèles installés (`ollama list`, via `/api/llm/models`) ; le modèle par défaut est présélectionné.
- Mêmes garde-fous que la CLI : profil draft, jamais « CONFORME » ; synthèse IA « à relire » ; à la validation d'un profil, décision explicite pour chaque champ et chaque renvoi, INVRAISEMBLABLE et règles plafonnées par une norme en rouge.

## Ce qu'il ne faut pas faire

- Ne pas invoquer FFmpeg via `os.system` avec des chaînes concaténées : utiliser `subprocess.run` avec une liste d'arguments.
- Ne pas charger tout le film en mémoire : traiter image par image ou par lots de N images.
- Ne pas ajouter de dépendance lourde (Torch, OpenCV) sans justification chiffrée.
- Ne pas inventer de valeurs de norme. En cas de doute sur une valeur, la laisser à `null` dans le profil et le signaler.
