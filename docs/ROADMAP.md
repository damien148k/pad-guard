# Feuille de route — pad-checker

Cinq phases. Chaque phase se termine par des tests qui passent et une démonstration sur une fixture. Ne pas commencer la phase suivante sans validation de Damien ou Vincent.

---

## Phase 0 : squelette du projet (une session)

**Livrables**
- `pyproject.toml`, structure `src/pad_checker/`, CLI `typer` avec les trois commandes (`analyze`, `report`, `validate-profile`) qui affichent « non implémenté ».
- Modèles pydantic du profil (§9 de SPEC) ; `validate-profile` fonctionne et refuse les champs inconnus.
- `tests/fixtures/make_fixtures.sh` qui génère avec FFmpeg :
  - `ok_prores.mov` : 20 s, 1080p25, ProRes 422 HQ, 10 bits, avec 5 s de mire EBU + 1 kHz à -18 dBFS, 5 s de noir, 10 s de `testsrc2` en plage légale, TC de départ 09:59:50:00, audio stéréo -23 LUFS.
  - `ok_dnxhr.mxf` : même contenu en DNxHR HQX.
  - `bad_levels.mov` : même base, avec 1 s de blanc à 100 % + 5 % (via `lutyuv`) et 1 s de noir sous 64.
  - `bad_audio.mov` : audio à -16 LUFS, pics à -0,5 dBTP.
  - `bad_structure.mov` : sans mire, TC de départ 00:00:00:00.
  - `wrong_codec.mov` : ProRes 422 LT.
  - `arte_ok.mov` : 20 s de programme **sans aucune amorce**, TC de départ 10:00:00:00, audio stéréo -23 LUFS, true peak < -1 dBTP, à tester avec `profiles/arte_hd_sdr.yaml`.
  - `arte_bad.mov` : même base, précédée de 5 s de mire (amorce interdite), avec une 2e paire audio entièrement silencieuse et un pic à -0,5 dBTP.
- CI locale : `uv run pytest` passe.

**Acceptation**
- `pad-checker validate-profile profiles/france_tv_hd.yaml` → OK ; une faute de frappe dans un champ → erreur nommant le champ.

---

## Phase 1 : probe et décodage (§4, §5.1)

**Livrables**
- `probe/` : `probe.json` complet, comparaison aux règles `format` du profil, table des pistes audio (flux, canal) → numéro de piste.
- `decode/` : itérateur PyAV qui livre `(frame_index, Y, Cb, Cr)` en `uint16` sans conversion de format, qui compte les images et collecte les erreurs de décodage (contrôle d'intégrité, sans second décodage), plus un itérateur audio par groupe de pistes.
- Benchmark `--benchmark` qui affiche les images/seconde de décodage seul.

**Acceptation**
- `wrong_codec.mov` est refusé avec un message qui nomme le codec trouvé et ceux attendus.
- Sur `ok_prores.mov`, `probe.json` contient `timecode = 09:59:50:00`, `pix_fmt = yuv422p10le`, `nb_frames = 500`.
- Décodage seul ≥ 4× temps réel sur la machine de développement (noter le chiffre dans le README).

---

## Phase 2 : moteur de mesures (§5.2, §5.3, §5.4)

**Livrables**
- `measure/video.py` : toutes les mesures par image du tableau §5.2, conversion RGB BT.709, préfiltre optionnel.
- `measure/audio.py` : loudness intégré, true peak, LRA, blocs momentanés, silences, phase, par groupe de pistes, en excluant tête et queue.
- `measurements.json` ou `.jsonl` écrit en flux (jamais tout en mémoire).
- Test de reproductibilité : deux analyses de la même fixture donnent des fichiers identiques.

**Acceptation**
- Sur `ok_prores.mov`, aucune image avec `y_above_pct > 1` ni `y_below_pct > 1` dans la partie programme.
- Sur `bad_levels.mov`, les 25 images de blanc clippé ont `y_above_pct > 90` et les 25 images de noir écrasé `y_below_pct > 90`.
- Sur `bad_audio.mov`, loudness intégré mesuré entre -16,5 et -15,5 LUFS, true peak > -1 dBTP.
- Performance globale (décodage + mesures) ≥ 2× temps réel ; sinon, profiler et optimiser avant de continuer.

---

## Phase 3 : structure, règles, verdict, rapport sans IA (§6, §7, §8)

**Livrables**
- `structure/` : mire + 1 kHz, noirs de tête/queue, timecode, images figées, noirs isolés, dupliquées, PSE simplifié.
- `rules/` : agrégation en événements, évaluateur d'expressions sécurisé, gravité, verdict, score.
- `report/` : `rapport.md` et `rapport.pdf` complets (toutes les sections §8 sauf la synthèse IA, remplacée par un texte généré par gabarit), graphiques en annexe, vignettes avec `--thumbnails`.
- Commande `report` qui régénère le rapport à partir des JSON.

**Acceptation**
- `ok_prores.mov` et `ok_dnxhr.mxf` → `CONFORME`, 0 événement `major` ou `blocking`.
- `bad_levels.mov` → `NON-CONFORME`, exactement 2 événements (`white_clip` et `black_crush`) avec les bons TC de début et de fin à l'image près.
- `bad_audio.mov` → `NON-CONFORME`, événements `audio_loudness` et `audio_true_peak`.
- `bad_structure.mov` → `NON-CONFORME`, événements `structure_bars` et `structure_timecode`.
- `arte_ok.mov` avec le profil Arte → `CONFORME` ; `arte_bad.mov` → `NON-CONFORME` avec `structure_bars_present`, `audio_silent_track` et `audio_true_peak`.
- Le PDF s'ouvre, est en français, et le tableau des anomalies tient sur la largeur de page.

**À ce stade l'outil est utilisable en production.** Faire une recette avec Vincent sur de vrais masters avant la Phase 4.

---

## Phase 4 : couche IA (§8.1)

**Livrables**
- `llm/` : interface `LLMClient` et implémentation `OllamaClient` (bibliothèque `ollama`, sortie forcée au schéma JSON, images jointes). Modèle par défaut `qwen3-vl:32b-instruct`, repli `qwen3-vl:8b-instruct`. Commande `pad-checker llm-check` qui vérifie qu'Ollama répond, que le modèle est installé et qu'il tient en VRAM.
- Prompt système versionné dans `llm/prompts/`, qui interdit explicitement toute modification du verdict.
- Synthèse rédigée insérée en section 3 du rapport ; colonne « qualification suggérée » remplie à partir des vignettes.
- Outil annexe `pad-checker draft-profile <pdf>` : propose un profil YAML à partir du PDF d'un diffuseur, avec tous les champs incertains marqués `# A VERIFIER`.

**Acceptation**
- Avec `--llm none`, le rapport est strictement identique à la Phase 3.
- Avec `--llm ollama` sur `bad_levels.mov`, le verdict et les événements sont identiques ; seules la synthèse et la colonne de qualification changent.
- Test unitaire avec un `LLMClient` factice : une réponse mal formée ou une panne réseau n'empêche pas la génération du rapport (synthèse remplacée par le gabarit, avertissement dans le rapport).

---

## Phase 5 : interface locale (hors SPEC v2, après validation)

**Livrables**
- Interface web locale (Gradio ou Streamlit, au choix justifié) : glisser un fichier, choisir un profil, lancer, suivre la progression, télécharger le PDF.
- Aucune logique métier dans l'interface : elle appelle la CLI ou les mêmes fonctions Python.

**Acceptation**
- Vincent produit un rapport sans ouvrir de terminal.

---

## Décisions ouvertes à trancher avec Vincent

1. Mapping audio : VO / VF / VI en trois paires stéréo pour Arte (confirmé le 7 octobre 2026) ; à confirmer pour les autres chaînes.
2. Structure de tête précise par chaîne (durées de mire, de noir, présence d'un carton).
3. Liste des chaînes à couvrir en priorité (un profil chacune).
4. Faut-il un contrôle des films en 24 i/s natifs avant conversion 25 i/s ? (hors périmètre v2 si non.)
5. ~~Modèle local ou API externe~~ Tranché le 7 octobre 2026 : Ollama local uniquement.
