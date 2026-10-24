# PAD Guard

Contrôle qualité automatisé de fichiers Prêt à Diffuser (ProRes 422 HQ / DNxHR HQX) pour Lumiris Production.

Voir `docs/SPEC.md` (spécification) et `docs/ROADMAP.md` (feuille de route).

## Installation

```bash
uv sync
```

FFmpeg 6+ et `ffprobe` doivent être dans le PATH.

La commande s'appelle `pad-guard` ; l'ancien nom `pad-checker` reste disponible comme alias.

## Interface locale

```bash
uv run pad-guard ui        # ouvre http://127.0.0.1:8765/ dans le navigateur
```

Choisir un film et un profil, suivre l'analyse, lire le rapport et télécharger le PDF, créer et valider le profil d'une chaîne depuis son PDF : voir `docs/GUIDE_VINCENT.md`. Le serveur n'écoute que sur 127.0.0.1, la page ne charge rien depuis Internet, les films sont lus sur place (le navigateur ne reçoit que leur chemin). Les analyses lancées depuis l'interface exécutent la CLI (`python -m pad_guard analyze … --progress-json`) et sont rangées dans `Documents\PAD Guard\analyses\` (réglable).

## Utilisation

```bash
uv run pad-guard validate-profile profiles/arte_hd_sdr.yaml   # schéma, normes héritées, cycles
uv run pad-guard explain-profile profiles/arte_hd_sdr.yaml    # profil effectif : origine de chaque valeur, conflits
uv run pad-guard draft-profile "diffuseurs/doc.pdf" --name nom   # profil brouillon tiré du PDF (Ollama local, SPEC §13)
uv run pad-guard review-profile profiles/drafts/nom.yaml      # relecture champ par champ, écrit profiles/nom.yaml validé
uv run pad-guard compare-profiles profiles/a.yaml profiles/b.yaml
uv run pad-guard analyze film.mov --profile profiles/arte_hd_sdr.yaml --out ./out/
uv run pad-guard analyze film.mov --profile profiles/arte_hd_sdr.yaml --out ./out/ --audio-map "VO:1-2,VF:3-4"
uv run pad-guard rerun ./out/                          # structure + règles + rapport, sans refaire les mesures
uv run pad-guard rerun ./out/ --from rules --profile autre.yaml   # autres règles sur les mêmes mesures
uv run pad-guard report ./out/                         # rapport seul (vignettes comprises)
```

`analyze` enchaîne probe, mesures, structure, règles et rapport. Le code de retour vaut 0 pour CONFORME, 4 pour NON-CONFORME, 1 pour une erreur d'usage ou un profil incomplet (détecté avant les mesures), 2 pour un fichier refusé.

Un profil hérite des normes de `normes/` citées dans `meta.extends` (SPEC §12) ; le profil effectif (profil + normes) est écrit dans `effective_profile.json` et son empreinte figure dans le rapport. Un profil en `meta.status: draft` donne un rapport « PROFIL NON VALIDÉ — résultat indicatif », jamais CONFORME. Les cadences 23,976, 24, 25, 29,97, 30, 50, 59,94 et 60 i/s sont mesurées ; un fichier que PAD Guard ne sait pas mesurer est refusé (code 2), un format que la chaîne n'accepte pas est une anomalie du rapport.

`rerun` repart des JSON du dossier : il réutilise le profil effectif `effective_profile.json` écrit par `analyze` (même si une norme a changé depuis), ou le profil donné par `--profile`. Un autre profil n'est accepté que s'il ne change aucun paramètre de mesure (seuils convertis en valeurs de code, préfiltre, seuil de flash, détection du balayage, plage programme, groupes audio) ; sinon il faut relancer `analyze`. Le fichier source n'est relu que pour la recherche de mire, le format d'image, le 1 kHz et les vignettes (quelques centaines d'images, par accès direct).

Les vignettes sont produites par défaut (`--no-thumbnails` pour s'en passer ; lors d'une relance sans le fichier source, elles sont sautées avec un avertissement, sauf `--thumbnails` explicite qui fait échouer) : une vignette par anomalie image (`vignettes/`) : l'image la plus mauvaise de l'événement, et pour les niveaux et le gamut une deuxième moitié où les pixels comptés par la mesure sont peints (rouge : Y au-dessus de la tolérance, bleu : en dessous, magenta : RVB hors limites).

`--audio-map` remplace, pour cette analyse, les groupes de pistes `audio.groups` du profil : `NOM:PISTES[:LAYOUT]` séparés par des virgules, avec des pistes en plage (`1-2`, `5-10`), seules (`7`) ou en liste (`1+3`). Le layout est repris du groupe du profil de même nom s'il a le même nombre de pistes, sinon déduit du nombre de pistes (1 `mono`, 2 `stereo`, 6 `5.1`) ; `dual_mono` se précise explicitement (`VO:1-2:dual_mono`). Tous les groupes donnés en ligne de commande sont obligatoires. Le mapping utilisé et sa source (profil ou ligne de commande) sont écrits dans `probe.json`.

### Fichiers produits dans `--out`

| Fichier | Étape | Contenu |
|---|---|---|
| `probe.json` | probe | métadonnées, table des pistes audio, mapping audio, contrôles de format |
| `measurements.json` | mesures | en-tête, intégrité, seuils appliqués (valeurs de code 10 bits), plage programme, loudness / true peak / LRA par groupe, niveaux par piste |
| `measurements_video.jsonl` | mesures | une ligne par image (`y_min` … `sat_max`, SPEC §5.2 ; `comb`, indicateur de peignage, SPEC §12.5) |
| `measurements_audio.jsonl` | mesures | une ligne par bloc de 100 ms et par groupe (`m`, `s`, `tp`, `peak`, `rms`, `clip`, `corr`, `diff`) |
| `structure.json` | structure | mire, 1 kHz, noirs de tête et de queue, programme, contrôles, images figées / dupliquées / noires isolées, PSE, format d'image |
| `events.json`, `verdict.json` | règles | événements avec gravité ; statut, score, compteurs, motifs |
| `rapport.md`, `rapport.pdf` | rapport | rapport en français (sections SPEC §8), `annexes/` (graphiques), `vignettes/` |
| `run.json`, `profile.yaml`, `effective_profile.json` | analyze | date et commande de l'analyse et des relances, heure de fin ; copie du fichier de profil ; profil effectif (valeurs, origine de chaque valeur, conflits, empreinte) |
| `rapport.json` | rapport | ce que montre `rapport.md`, en données, pour l'interface ; anomalies nommées par leur clé `type@image@groupe` |
| `progression.jsonl`, `ui_job.json` | interface | progression écrite par `--progress-json` ; état de la tâche lancée depuis l'interface |

`measurements.json` est écrit en dernier : s'il est présent, les deux fichiers `.jsonl` sont complets. Les mesures sont au format 2 depuis la Phase 3 (différences entre images `d_mean`, `d_up_pct`, `d_down_pct`) : un dossier mesuré avant doit être réanalysé. Format 3 depuis la Phase 4a (indicateur de peignage `comb` et balayage détecté `scan`) : idem.

## Performances

Vitesse de décodage seul (`analyze --benchmark`), 1920×1080 25p, 500 images, mesurée le 7 octobre 2026 sur la machine de développement (AMD Zen 3, 16 cœurs / 32 threads, Windows 11, Python 3.12, PyAV 19.0.1), fichier dans le cache disque :

| Fichier | Débit | Images/s | × temps réel |
|---|---|---|---|
| ProRes 422 HQ, testsrc2 + grain (proche d'un master réel) | 190 Mbit/s | 762 | 30× |
| DNxHR HQX, même contenu | 184 Mbit/s | 900 | 36× |
| ProRes 422 HQ, `ok_prores.mov` (synthétique, très compressible) | 60 Mbit/s | 1755 | 70× |

Analyse complète décodage + mesures (`analyze`, Phase 2), même machine, 60 s ProRes 422 HQ `testsrc2` + grain (190 Mbit/s) avec 6 pistes mono 24 bits : **11,2 s, soit 5,4× le temps réel** (vidéo 8,2 s à 183 i/s avec 8 processus de mesure, audio 3,0 s). Extrapolé à un film de 90 min : environ 17 min. Objectif Phase 2 : ≥ 2× temps réel.

Phase 3 (8 octobre 2026) : les différences entre images (figées, dupliquées, PSE) sont calculées pendant la même passe. Même fichier : **14 s, soit 4,3× le temps réel** (6,3× sans ces différences, mesuré dans les mêmes conditions). Structure, règles et rapport ajoutent quelques secondes (accès direct à quelques centaines d'images).

Les mesures vidéo tournent dans des processus séparés (`--workers`, 8 par défaut sur 16 cœurs ; au-delà, aucun gain mesuré) qui reçoivent les images décodées par mémoire partagée : le fichier reste lu séquentiellement par un seul décodeur. Le nombre de processus ne change pas les résultats (testé à l'octet près).

Objectif Phase 1 : ≥ 4× temps réel. À 30× temps réel, la lecture d'un ProRes HQ demande environ 700 Mo/s : sur un vrai film, le disque (NAS, disque dur, SSD SATA) sera probablement le facteur limitant, pas le décodage.

## Tests

```bash
bash tests/fixtures/make_fixtures.sh   # génère les fichiers vidéo de test (fait aussi automatiquement par pytest)
uv run pytest
uv run playwright install chromium     # une fois, pour le test de l'interface dans un vrai navigateur
uv run pytest -m e2e                   # ce test n'est pas lancé par défaut
```
