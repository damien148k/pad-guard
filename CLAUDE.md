# PAD Guard

Outil de contrôle qualité automatisé de fichiers Prêt à Diffuser (PAD) pour **Lumiris Production** (restauration d'images). Il analyse un master **ProRes 422 HQ** ou **DNxHR HQX**, mesure les niveaux vidéo et audio, vérifie la structure du fichier (mire, noirs, timecode), compare le tout au profil de la chaîne cliente et produit un rapport.

Utilisateur final : **Vincent**, responsable technique. Il n'est pas développeur. Il veut déposer un fichier, choisir une chaîne et lire un rapport clair.

La spécification complète est dans `docs/SPEC.md`. La feuille de route et les critères d'acceptation sont dans `docs/ROADMAP.md`. Lis les deux avant de coder.

## Principes non négociables

1. **Verdict déterministe.** Le statut CONFORME / NON-CONFORME, le score et la gravité de chaque anomalie sont calculés par des règles. L'IA ne touche jamais au verdict ; elle rédige la synthèse et propose des qualifications que l'humain valide.
2. **Le cahier des charges du client fait foi ; les normes informent et complètent** (décision de Damien, 23 octobre 2026). Tout seuil vient du profil effectif, résolu de façon déterministe à partir de `profiles/*.yaml` et des `normes/*.yaml` dont il hérite (priorité : profil diffuseur > `lumiris_maison` > normes internationales, dans l'ordre de `extends`). Le profil effectif est écrit dans `out/effective_profile.json` avec l'origine de chaque valeur.
   - Une valeur fixée par le client s'applique telle quelle, et figure dans le profil du client avec sa citation, même si une norme dit la même chose. Si une norme diffère, le rapport l'indique en information (« Arte : 103 % ; EBU R 103 : 105 % »), sans effet sur le verdict. Un écart avec une norme n'est jamais une raison de marquer A VERIFIER.
   - Une valeur absente chez le client mais présente dans une norme s'applique comme recommandation (source NORME) : toute anomalie qui en dépend est plafonnée à `minor`, comme DEDUIT. Une norme seule ne rend jamais un PAD NON-CONFORME. Les règles maison (`lumiris_maison`) ne sont pas des normes : elles gardent leur gravité.
   - Méthode de mesure non précisée par le client (préfiltre, fenêtres, gating) : suivre la norme plutôt qu'un choix maison.
   - « A VERIFIER » veut dire uniquement : valeur sans citation du document du client. Aucune valeur de norme n'est codée en dur. Si une valeur manque dans le profil effectif, l'outil refuse de tourner avec un message clair. Le profil de référence est `profiles/arte_hd_sdr.yaml` : chaque valeur propre à Arte y cite le paragraphe des consignes Arte V2 ; les chaînes diffèrent sur des points importants (Arte : pas d'amorce, true peak -1 dBTP ; usage CST français : amorce, -3 dBTP), donc ne jamais supposer qu'une règle est universelle.
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
- Couche IA : **Ollama uniquement** (bibliothèque Python `ollama`), modèle par défaut `qwen3-vl:32b-instruct`, repli `qwen3-vl:8b-instruct`, derrière une interface `LLMClient` (pour pouvoir brancher un autre moteur local plus tard). Pas d'API externe. Désactivée par défaut. Deux usages : la synthèse du rapport (Phase 4c) et l'extraction d'un profil brouillon depuis le PDF d'un diffuseur (`draft-profile`, Phase 4b), toujours en `A_VERIFIER`.
- Lecture des PDF (Phase 4b) : `pdfplumber` (texte) et `pypdfium2` (rendu des pages). Pas de PyMuPDF pour cet usage (licence AGPL).

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
  report/     génération Markdown / PDF
  llm/        LLMClient et OllamaClient (seule implémentation), consignes versionnées dans llm/prompts/
  draft/      draft-profile (lecture du PDF, schéma d'extraction, contrôle des citations), review-profile, compare-profiles
  cli.py      point d'entrée `pad-guard`
```

Le flux est strictement linéaire : `profil effectif -> probe -> decode+measure -> structure -> rules -> report`, avec un fichier JSON écrit entre chaque étape dans le dossier de travail (`effective_profile.json`, `probe.json`, `measurements.json`…). Chaque étape doit pouvoir être relancée seule à partir du JSON précédent.

## Conventions

- Code et commentaires en anglais, messages utilisateur et rapport en français.
- Timecodes au format `HH:MM:SS:FF` ; en interne, stocker aussi le numéro d'image absolu.
- La cadence et le balayage du fichier d'entrée ne sont pas maîtrisés (ils dépendent du client) ; ils sont lus dans `probe.json` (`r_frame_rate`, `avg_frame_rate`, `field_order`) et confirmés par une détection de peignage pendant le décodage. Jusqu'à la Phase 6, seul le 25 i/s est pris en charge pour les mesures : toute autre cadence fait refuser l'analyse avec un message qui nomme la cadence trouvée. Aucun 25 ne doit plus être écrit en dur dans le code à partir de maintenant : utiliser la cadence de `probe.json`.
- Niveaux vidéo exprimés en valeurs de code **10 bits** dans le JSON, et en pourcentage dans le rapport. Pour un fichier 8 bits (ne devrait pas arriver avec ces codecs), convertir en 10 bits avant toute comparaison.
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
uv run pad-guard validate-profile profiles/arte_hd_sdr.yaml   # schéma, normes héritées, cycles
uv run pad-guard explain-profile profiles/arte_hd_sdr.yaml    # chaque valeur, son origine, les conflits
uv run pad-guard draft-profile diffuseurs/doc.pdf --name nom  # brouillon dans profiles/drafts/ (Ollama local)
uv run pad-guard review-profile profiles/drafts/nom.yaml      # relecture champ par champ -> profiles/nom.yaml validé
uv run pad-guard compare-profiles a.yaml b.yaml               # différences entre deux profils effectifs
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
