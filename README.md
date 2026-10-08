# pad-checker

Contrôle qualité automatisé de fichiers Prêt à Diffuser (ProRes 422 HQ / DNxHR HQX) pour Lumiris Production.

Voir `docs/SPEC.md` (spécification) et `docs/ROADMAP.md` (feuille de route).

## Installation

```bash
uv sync
```

FFmpeg 6+ et `ffprobe` doivent être dans le PATH.

## Utilisation

```bash
uv run pad-checker validate-profile profiles/arte_hd_sdr.yaml
uv run pad-checker analyze film.mov --profile profiles/arte_hd_sdr.yaml --out ./out/
uv run pad-checker analyze film.mov --profile profiles/arte_hd_sdr.yaml --out ./out/ --audio-map "VO:1-2,VF:3-4"
uv run pad-checker report ./out/
```

`--audio-map` remplace, pour cette analyse, les groupes de pistes `audio.groups` du profil : `NOM:PISTES[:LAYOUT]` séparés par des virgules, avec des pistes en plage (`1-2`, `5-10`), seules (`7`) ou en liste (`1+3`). Le layout est repris du groupe du profil de même nom s'il a le même nombre de pistes, sinon déduit du nombre de pistes (1 `mono`, 2 `stereo`, 6 `5.1`) ; `dual_mono` se précise explicitement (`VO:1-2:dual_mono`). Tous les groupes donnés en ligne de commande sont obligatoires. Le mapping utilisé et sa source (profil ou ligne de commande) sont écrits dans `probe.json`.

### Fichiers produits dans `--out`

| Fichier | Étape | Contenu |
|---|---|---|
| `probe.json` | probe | métadonnées, table des pistes audio, mapping audio, contrôles de format |
| `measurements.json` | mesures | en-tête, intégrité, seuils appliqués (valeurs de code 10 bits), plage programme, loudness / true peak / LRA par groupe, niveaux par piste |
| `measurements_video.jsonl` | mesures | une ligne par image (`y_min` … `sat_max`, SPEC §5.2) |
| `measurements_audio.jsonl` | mesures | une ligne par bloc de 100 ms et par groupe (`m`, `s`, `tp`, `peak`, `rms`, `clip`, `corr`, `diff`) |

`measurements.json` est écrit en dernier : s'il est présent, les deux fichiers `.jsonl` sont complets.

## Performances

Vitesse de décodage seul (`analyze --benchmark`), 1920×1080 25p, 500 images, mesurée le 7 octobre 2026 sur la machine de développement (AMD Zen 3, 16 cœurs / 32 threads, Windows 11, Python 3.12, PyAV 19.0.1), fichier dans le cache disque :

| Fichier | Débit | Images/s | × temps réel |
|---|---|---|---|
| ProRes 422 HQ, testsrc2 + grain (proche d'un master réel) | 190 Mbit/s | 762 | 30× |
| DNxHR HQX, même contenu | 184 Mbit/s | 900 | 36× |
| ProRes 422 HQ, `ok_prores.mov` (synthétique, très compressible) | 60 Mbit/s | 1755 | 70× |

Analyse complète décodage + mesures (`analyze`, Phase 2), même machine, 60 s ProRes 422 HQ `testsrc2` + grain (190 Mbit/s) avec 6 pistes mono 24 bits : **11,2 s, soit 5,4× le temps réel** (vidéo 8,2 s à 183 i/s avec 8 processus de mesure, audio 3,0 s). Extrapolé à un film de 90 min : environ 17 min. Objectif Phase 2 : ≥ 2× temps réel.

Les mesures vidéo tournent dans des processus séparés (`--workers`, 8 par défaut sur 16 cœurs ; au-delà, aucun gain mesuré) qui reçoivent les images décodées par mémoire partagée : le fichier reste lu séquentiellement par un seul décodeur. Le nombre de processus ne change pas les résultats (testé à l'octet près).

Objectif Phase 1 : ≥ 4× temps réel. À 30× temps réel, la lecture d'un ProRes HQ demande environ 700 Mo/s : sur un vrai film, le disque (NAS, disque dur, SSD SATA) sera probablement le facteur limitant, pas le décodage.

## Tests

```bash
bash tests/fixtures/make_fixtures.sh   # génère les fichiers vidéo de test (fait aussi automatiquement par pytest)
uv run pytest
```
