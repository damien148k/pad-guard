# Prompt de démarrage pour Claude Code

Copie le texte ci-dessous dans Claude Code (Opus 5.5 ou Sonnet 5.5), après avoir placé les fichiers de ce dossier à la racine d'un dépôt vide :

```
pad-checker/
├── CLAUDE.md
├── docs/
│   ├── SPEC.md
│   ├── ROADMAP.md
│   ├── ANALYSE_ARTE.md
│   └── REVUE_INITIALE.md
└── profiles/
    ├── arte_hd_sdr.yaml
    └── france_tv_hd.yaml
```

---

## Texte à coller

> Tu démarres le projet **pad-checker** : un outil en ligne de commande, en Python, qui contrôle la conformité de fichiers vidéo ProRes 422 HQ et DNxHR HQX par rapport aux normes de Prêt à Diffuser des chaînes de télévision françaises et des plateformes.
>
> Lis d'abord `CLAUDE.md`, puis `docs/SPEC.md` en entier, puis `docs/ROADMAP.md`. Le profil de référence est `profiles/arte_hd_sdr.yaml` (construit à partir des consignes Arte V2, voir `docs/ANALYSE_ARTE.md`) ; `profiles/france_tv_hd.yaml` est un second exemple.
>
> Commence par la **Phase 1** de la feuille de route et ne passe à la phase suivante que lorsque les critères d'acceptation de la phase en cours sont remplis et que les tests passent. À la fin de chaque phase, résume ce qui est fait, ce qui reste ouvert, et attends ma validation.
>
> Règles importantes :
> - Le verdict CONFORME / NON-CONFORME est calculé par des règles déterministes. Aucune IA n'intervient dans le verdict.
> - Tous les seuils viennent du profil YAML, jamais du code.
> - Chaque mesure doit être reproductible : deux exécutions sur le même fichier donnent le même JSON.
> - Si la spécification est ambiguë ou si tu détectes une erreur technique dedans, signale-le avant de coder, ne contourne pas en silence.
> - Ne fabrique pas de fichiers vidéo de test lourds : génère des fichiers courts (10 à 20 secondes) avec FFmpeg (`testsrc2`, `smptehdbars`, `color`) dans `tests/fixtures/`, via un script `make_fixtures.sh`.
>
> Pose-moi tes questions maintenant si quelque chose t'empêche de démarrer la Phase 1 ; sinon, commence.

---

## Conseils d'utilisation

- **Une phase par session** fonctionne mieux qu'un seul gros prompt. Démarre une nouvelle conversation à chaque phase en disant : « Continue avec la Phase N de `docs/ROADMAP.md` ».
- **Fournis un vrai fichier de test** dès que possible (un extrait de 30 secondes d'un vrai master, avec mire et noirs de tête). Les fichiers synthétiques ne couvrent pas tout.
- **Garde `CLAUDE.md` à jour** quand une décision change : c'est le fichier que Claude Code relit à chaque session.
- **Fournis le PDF de la chaîne** lorsque tu demandes à Claude de créer un nouveau profil YAML, et relis le résultat avant de l'utiliser.
