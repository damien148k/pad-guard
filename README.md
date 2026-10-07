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
uv run pad-checker report ./out/
```

## Performances

Vitesse de décodage seul (`analyze --benchmark`), 1920×1080 25p, 500 images, mesurée le 7 octobre 2026 sur la machine de développement (AMD Zen 3, 16 cœurs / 32 threads, Windows 11, Python 3.12, PyAV 19.0.1), fichier dans le cache disque :

| Fichier | Débit | Images/s | × temps réel |
|---|---|---|---|
| ProRes 422 HQ, testsrc2 + grain (proche d'un master réel) | 190 Mbit/s | 762 | 30× |
| DNxHR HQX, même contenu | 184 Mbit/s | 900 | 36× |
| ProRes 422 HQ, `ok_prores.mov` (synthétique, très compressible) | 60 Mbit/s | 1755 | 70× |

Objectif Phase 1 : ≥ 4× temps réel. À 30× temps réel, la lecture d'un ProRes HQ demande environ 700 Mo/s : sur un vrai film, le disque (NAS, disque dur, SSD SATA) sera probablement le facteur limitant, pas le décodage.

## Tests

```bash
bash tests/fixtures/make_fixtures.sh   # génère les fichiers vidéo de test (fait aussi automatiquement par pytest)
uv run pytest
```
