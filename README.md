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

## Tests

```bash
bash tests/fixtures/make_fixtures.sh   # génère les fichiers vidéo de test (fait aussi automatiquement par pytest)
uv run pytest
```
