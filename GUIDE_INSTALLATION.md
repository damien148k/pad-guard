# Guide pas à pas : préparer Claude Code et coder pad-checker

Ce guide suppose une station Windows 11 ou Linux (Ubuntu) avec la RTX 4090. Les commandes Windows se tapent dans **PowerShell**, les commandes Linux dans un **terminal**.

---

## Étape 1 : récupérer le dossier

1. Télécharge `pad-checker-docs.zip` depuis le fil du projet (pièce jointe du message).
2. Crée un dossier de travail, par exemple `C:\dev\pad-checker` (Windows) ou `~/dev/pad-checker` (Linux).
3. Décompresse le zip **dans** ce dossier. Tu dois obtenir exactement :

```
pad-checker/
├── 00_PROMPT_DEMARRAGE.md
├── GUIDE_INSTALLATION.md
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

`CLAUDE.md` doit être à la racine : c'est le fichier que Claude Code lit automatiquement à chaque session.

---

## Étape 2 : installer les outils

| Outil | Pourquoi | Windows | Linux (Ubuntu) |
|---|---|---|---|
| Git | historique du code, retour arrière | `winget install Git.Git` | `sudo apt install git` |
| Python 3.11+ | langage du projet | `winget install Python.Python.3.12` | `sudo apt install python3.12 python3.12-venv` |
| uv | dépendances Python | `winget install astral-sh.uv` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| FFmpeg 6+ | décodage et mesures | `winget install Gyan.FFmpeg` | `sudo apt install ffmpeg` |
| Node.js 20+ | requis par Claude Code | `winget install OpenJS.NodeJS.LTS` | `sudo apt install nodejs npm` |
| Claude Code | l'agent qui code | `npm install -g @anthropic-ai/claude-code` | `npm install -g @anthropic-ai/claude-code` |
| Ollama | LLM local (Phase 4 seulement) | `winget install Ollama.Ollama` | `curl -fsSL https://ollama.com/install.sh \| sh` |

Ferme et rouvre le terminal, puis vérifie :

```bash
git --version
python --version      # 3.11 ou plus
uv --version
ffmpeg -version       # 6.0 ou plus
claude --version
ollama --version
```

Si une commande n'est pas trouvée, c'est presque toujours le PATH : rouvre le terminal, ou redémarre la session Windows.

---

## Étape 3 : télécharger le modèle LLM (peut se faire plus tard)

Utile seulement en Phase 4, mais le téléchargement est long (≈ 20 Go) :

```bash
ollama pull qwen3-vl:32b-instruct
ollama pull qwen3-vl:8b-instruct
```

Test rapide :

```bash
ollama run qwen3-vl:8b-instruct "Réponds en une phrase : qu'est-ce qu'un PAD en télévision ?"
```

Pendant que le 32B tourne, `nvidia-smi` doit montrer environ 20 Go de VRAM utilisés.

---

## Étape 4 : initialiser le dépôt Git

Dans le dossier `pad-checker` :

```bash
git init
git add .
git commit -m "Documentation initiale pad-checker"
```

Ce premier commit te permet de revenir en arrière à tout moment si Claude Code part dans une mauvaise direction (`git diff` pour voir les changements, `git checkout .` pour les annuler).

Optionnel mais conseillé : crée un dépôt privé sur GitHub et pousse-le, pour avoir une sauvegarde.

---

## Étape 5 : lancer Claude Code

```bash
cd C:\dev\pad-checker     # ou ~/dev/pad-checker
claude
```

À la première ouverture, Claude Code te demande de te connecter avec ton compte Claude (navigateur). Ensuite :

1. Tape `/model` et choisis **Opus 5.5** pour les phases 0 à 3 (architecture et moteur de mesures : c'est là que la qualité compte). Sonnet 5.5 suffit pour la Phase 5 (interface) et les corrections simples.
2. Vérifie que Claude a bien lu le contexte : tape `Résume en 5 lignes ce que tu sais du projet.` Il doit parler de ProRes/DNxHR, du profil Arte, du verdict déterministe et d'Ollama. Sinon, `CLAUDE.md` n'est pas à la racine.

---

## Étape 6 : démarrer la Phase 0

Ouvre `00_PROMPT_DEMARRAGE.md`, copie le bloc « Texte à coller » et colle-le dans Claude Code.

Claude va proposer des modifications et des commandes. Au début, lis ce qu'il propose avant d'accepter. Quand tu es à l'aise, tu peux autoriser les commandes répétitives (`uv`, `pytest`, `ffmpeg`) pour qu'il ne te les demande plus.

À la fin de la phase, Claude doit te présenter un résumé. Vérifie toi-même :

```bash
uv run pytest
uv run pad-checker validate-profile profiles/arte_hd_sdr.yaml
```

Si tout passe :

```bash
git add .
git commit -m "Phase 0 terminée"
```

---

## Étape 7 : enchaîner les phases

Pour chaque phase suivante (1 à 5) :

1. Quitte Claude Code (`/exit`) et relance `claude` : **une session neuve par phase** évite que le contexte se dégrade.
2. Tape : `Continue avec la Phase N de docs/ROADMAP.md. Relis CLAUDE.md et la section correspondante de docs/SPEC.md avant de commencer.`
3. Laisse-le travailler ; réponds à ses questions.
4. Vérifie les critères d'acceptation listés dans `docs/ROADMAP.md` pour cette phase.
5. `git commit` quand c'est validé.

Points d'attention par phase :

| Phase | À vérifier toi-même |
|---|---|
| 1 | `wrong_codec.mov` est bien refusé ; le chiffre de vitesse de décodage est noté dans le README |
| 2 | Lance une analyse sur **un vrai master ProRes** (un extrait de quelques minutes) et regarde si les valeurs de Y ont du sens par rapport à ce que montre ton oscilloscope |
| 3 | Compare le rapport à un contrôle que Vincent a fait à la main sur le même fichier. C'est la vraie recette |
| 4 | `ollama serve` doit tourner ; essaie aussi en coupant Ollama : le rapport doit sortir quand même |
| 5 | Vincent doit pouvoir produire un rapport seul |

---

## Étape 8 : bonnes pratiques pendant le développement

- **Si Claude se trompe sur une norme**, corrige-le en citant le paragraphe Arte, puis demande-lui de mettre à jour `CLAUDE.md` pour que l'erreur ne revienne pas.
- **Si une décision change** (nouvelle chaîne, nouveau format audio), modifie d'abord `docs/SPEC.md` ou le profil YAML, puis demande à Claude d'implémenter le changement.
- **Garde les vrais masters hors du dépôt Git** : ajoute un dossier `samples/` dans `.gitignore` et mets-y tes extraits de test.
- **`/clear`** remet à zéro la conversation sans quitter Claude Code, utile entre deux tâches distinctes.
- **`git log`** et **`git diff`** sont tes meilleurs amis pour voir ce que Claude a changé.

---

## En cas de problème

| Symptôme | Cause probable | Solution |
|---|---|---|
| `claude: command not found` | npm pas dans le PATH | rouvrir le terminal ; sous Windows, redémarrer la session |
| FFmpeg ne lit pas le ProRes | build FFmpeg trop ancien ou minimal | installer la build complète (Gyan.FFmpeg ou paquet Ubuntu récent) |
| Ollama « out of memory » avec le 32B | autre programme sur le GPU (Resolve, navigateur) | fermer DaVinci Resolve, ou passer sur `qwen3-vl:8b-instruct` |
| Claude ignore une règle de `CLAUDE.md` | session trop longue | `/exit`, relancer, et rappeler la règle en une phrase |
| Les tests passent mais les mesures semblent fausses sur un vrai fichier | fixtures synthétiques trop simples | ajouter un extrait réel dans `tests/fixtures/` (court) et demander un test dessus |
