# _archives — fichiers retirés, gardés pour la traçabilité

Rien ici n'est lu par PAD Guard : l'analyse, `draft-profile`, `review-profile` et l'interface ne lisent que
`profiles/`, `profiles/drafts/`, `normes/`, `normes/drafts/` et `diffuseurs/` (motifs non récursifs).
Ne jamais créer ici de dossier nommé `normes` ni `profiles/../normes` : un profil ou un brouillon de norme
rangé dessous y chercherait ses normes.

Les PDF ne sont pas versionnés (`.gitignore`), comme dans `normes/sources/` et `diffuseurs/`.

Audit du 25 octobre 2026 :

| Chemin | Origine | Raison |
|---|---|---|
| `00_PROMPT_DEMARRAGE.md` | racine | prompt de démarrage du 7/10/2026, décrit l'arborescence initiale |
| `docs/REVUE_INITIALE.md` | `docs/` | relecture critique du cahier des charges initial (7/10/2026) |
| `profiles_drafts/france_tv_hd_2026-10-24/` | `profiles/drafts/` | brouillon France TV du 24/10 (modèle 8b) et réponses de relecture du 25/10 : base du profil provisoire, à refaire depuis l'annexe CDE 2023 |
| `diffuseurs/spécificités-techniques-du-numérique-2021.pdf` | `diffuseurs/` | régie publicitaire francetvpub, hors sujet |
| `normes_sources/…` | `normes/sources/` | doublon, version remplacée, document retiré ou incomplet : voir `normes/sources/README.md` |
