# Feuille de route — PAD Guard

Orientation v3 du 23 octobre 2026 : multi-diffuseurs, profils hérités de normes. Chaque phase se termine par des tests qui passent et une démonstration sur une fixture. Ne pas commencer la phase suivante sans validation de Damien ou Vincent.

---

## Phase 0 : squelette du projet (une session) — terminée

**Livrables**
- `pyproject.toml`, structure `src/pad_guard/`, CLI `typer` avec les trois commandes (`analyze`, `report`, `validate-profile`) qui affichent « non implémenté ».
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
- `pad-guard validate-profile profiles/france_tv_hd.yaml` → OK ; une faute de frappe dans un champ → erreur nommant le champ.

---

## Phase 1 : probe et décodage (§4, §5.1) — terminée

**Livrables**
- `probe/` : `probe.json` complet, comparaison aux règles `format` du profil, table des pistes audio (flux, canal) → numéro de piste.
- `decode/` : itérateur PyAV qui livre `(frame_index, Y, Cb, Cr)` en `uint16` sans conversion de format, qui compte les images et collecte les erreurs de décodage (contrôle d'intégrité, sans second décodage), plus un itérateur audio par groupe de pistes.
- Benchmark `--benchmark` qui affiche les images/seconde de décodage seul.

**Acceptation**
- `wrong_codec.mov` est refusé avec un message qui nomme le codec trouvé et ceux attendus.
- Sur `ok_prores.mov`, `probe.json` contient `timecode = 09:59:50:00`, `pix_fmt = yuv422p10le`, `nb_frames = 500`.
- Décodage seul ≥ 4× temps réel sur la machine de développement (noter le chiffre dans le README).

---

## Phase 2 : moteur de mesures (§5.2, §5.3, §5.4) — terminée

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

## Phase 3 : structure, règles, verdict, rapport sans IA (§6, §7, §8) — terminée

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

## Phase 4a : normes et héritage de profils (sans IA)

**Livrables**
- Dossier `normes/` : fichiers YAML de même schéma que les profils, mais partiels, avec `meta.kind: norm`, `meta.document` (titre et version exacte) et une source (document + paragraphe) pour chaque valeur. Pour commencer : `ebu_r128.yaml`, `ebu_r103.yaml` et `lumiris_maison.yaml` (règles internes Lumiris). Les PDF sources sont dans `normes/sources/` (non versionné, inventaire dans son `README.md`). BT.709, BT.2100 et BT.2408 viendront aux phases 6 et 7.
- Profils : `meta.extends` (normes héritées), `meta.status` (`draft` | `validated`, `draft` par défaut), `meta.validated_by`, `meta.validated_at`, `meta.source_pdf`, `meta.source_pdf_sha256`. `validate-profile` vérifie que chaque norme citée existe et refuse les cycles.
- Résolution déterministe (`src/pad_guard/profiles/`) : fusion champ par champ, le dernier niveau gagne (normes dans l'ordre de `extends`, puis `lumiris_maison`, puis le profil). Profil effectif complet, chaque valeur avec son origine (fichier + source) ; conflits listés. Un `null` du profil effectif fait refuser l'analyse.
- `analyze` et `rerun` écrivent `effective_profile.json` (sans date, clés triées) et utilisent le profil effectif ; le rapport donne le nom du profil, son statut et l'empreinte SHA-256 du profil effectif.
- Commande `pad-guard explain-profile <profil.yaml>` : chaque valeur, son origine, les conflits.
- `profiles/arte_hd_sdr.yaml` réécrit avec `extends: [ebu_r128, ebu_r103, lumiris_maison]` (statut `validated`) ; `profiles/france_tv_hd.yaml` de même (statut `draft`).
- Profil `draft` : le rapport porte « PROFIL NON VALIDÉ — résultat indicatif » et n'affiche jamais CONFORME.
- Cadence et balayage : cadence (fraction exacte) et `field_order` lus par `probe`, indicateur de peignage par image pendant la passe de mesure, `scan_detected` (`progressive` | `interlaced` | `undetermined`) et avertissement si le drapeau et la détection ne concordent pas. Toute cadence autre que 25 i/s est refusée (jusqu'à la Phase 6). Section « Livraison » du rapport et événement `delivery_conversion_required` (info) quand le master diffère de `format.delivery`.

**Acceptation**
- Le profil effectif d'`arte_hd_sdr.yaml` réécrit est identique, valeur par valeur, à l'ancien profil (copie dans `tests/profiles/`).
- Les rapports des fixtures de la Phase 3 sont inchangés, hormis les lignes nouvelles (profil, statut, empreinte, livraison, balayage).
- Tests de priorité, de conflit, de norme manquante, de cycle et de `null` hérité (refus).
- Profil `draft` : jamais « CONFORME » dans le rapport.
- Fixture entrelacée → `scan_detected = interlaced` ; `ok_prores.mov` → `progressive` ; master 25p comparé à une livraison 50i → événement info `delivery_conversion_required`, verdict inchangé ; fixture à 24 i/s → refus nommant la cadence.

---

## Phase 4b : `draft-profile` depuis un PDF diffuseur

**Livrables**
- Extraction du texte du PDF (`pdfplumber`) et rendu des pages en images (`pypdfium2`). Pas de PyMuPDF (licence AGPL).
- Qwen3-VL via Ollama (local) avec sortie JSON contrainte par un schéma généré depuis le modèle pydantic du profil. Chaque valeur proposée porte `value`, `page`, `quote` et `status: A_VERIFIER`.
- Contrôle déterministe de chaque proposition : la citation doit exister dans le texte du PDF (normalisation des espaces, césures et ligatures) et contenir la valeur numérique ; sinon `value: null` et signalement. PDF sans couche texte : « citation non vérifiable » partout. Aucun champ deviné.
- Le profil brouillon est écrit en `meta.status: draft`, avec `meta.source_pdf` (dans `diffuseurs/`) et `meta.source_pdf_sha256`.
- Commande `pad-guard review-profile` qui fait passer `meta.status` de `draft` à `validated`, avec `validated_by` et `validated_at`.

**Acceptation**
- Sur le PDF Arte V2, toute valeur proposée a une citation vérifiée, et la comparaison automatique avec `profiles/arte_hd_sdr.yaml` ne montre aucune valeur fausse non signalée.

---

## Phase 4c : synthèse IA du rapport (§8.1)

**Livrables**
- `llm/` : interface `LLMClient` et implémentation `OllamaClient` (bibliothèque `ollama`, sortie forcée au schéma JSON, images jointes), communes avec `draft-profile`. Modèle par défaut `qwen3-vl:8b-instruct` depuis le 25 octobre 2026 (32B trop lent sur la RTX 3080 Ti, recette ponctuelle seulement ; avant : 32B, repli 8B). Aucun autre moteur, aucune API externe. Fait.
- Options `--llm none|ollama`, `--llm-model`, `--llm-refresh` sur `analyze`, `rerun` et `report`. Fait.
- Prompt système versionné `llm/prompts/synthese_v1.md`, qui interdit explicitement toute modification du verdict. Fait.
- `report/ai.py` : une requête par événement à vignette (vision), une par famille d'événements sans vignette, une pour la synthèse ; contrôles déterministes de tout ce que le modèle écrit (SPEC §8.1), repli sur le gabarit avec avertissement ; `llm_synthese.json` rejoué tant que l'empreinte ne change pas. Fait.
- Synthèse rédigée insérée en section 3 du rapport ; colonne « qualification suggérée » en italique, justification dans le détail ; « Méthodes et limites » mise à jour. Fait.
- Reste : commande `pad-guard llm-check` (Ollama répond, modèle installé, tient en VRAM).

**Acceptation**
- Avec `--llm none`, le rapport est strictement identique à la Phase 3.
- Avec `--llm ollama` sur `bad_levels.mov`, le verdict et les événements sont identiques ; seules la synthèse et la colonne de qualification changent.
- Test unitaire avec un `LLMClient` factice : une réponse mal formée ou une panne réseau n'empêche pas la génération du rapport (synthèse remplacée par le gabarit, avertissement dans le rapport). Fait (`tests/test_ai.py`).
- Recette du 24 octobre 2026 sur le vrai master Arte (`qwen3-vl:8b-instruct`, RTX 3080 Ti) : `events.json` et `verdict.json` identiques à l'octet avant et après, 33 requêtes en 77 s, synthèse retenue, 37 qualifications retenues et 19 vidées (justification des silences VF : « respectent le seuil »), relance sans appel au modèle.

---

## Phase 5 : interface locale (hors SPEC v2, après validation)

**Livrables**
- `pad-guard ui` : interface web locale d'après la maquette Claude Design (`design/maquette/`), servie par Starlette + uvicorn sur 127.0.0.1 seulement. Gradio et Streamlit écartés : ni l'un ni l'autre ne sert cette maquette ni ne transmet un chemin choisi dans la boîte de dialogue Windows. Fait.
- Choisir un film (par son chemin : jamais copié par le navigateur) et un profil, vérifier le récapitulatif (format lu par probe, exigences du profil avec leur source, correspondance audio vérifiée par `audio_map`), lancer, suivre la progression, annuler, lire le rapport (`rapport.json`), télécharger le PDF. Fait.
- Dépôt du PDF d'un diffuseur (reconnu par son SHA-256, sinon `draft-profile` en tâche) et écran de validation du profil brouillon (fonctions de `review-profile`, décision explicite par champ). Fait.
- Aucune logique métier dans l'interface : elle lance la CLI (`--progress-json`) ou appelle les mêmes fonctions Python. Fait.
- Surbrillance de la citation sur l'aperçu de page du PDF (position des mots par pdfplumber, même normalisation que le contrôle des citations). Fait.

**Écarts acceptés avec la maquette** (24 octobre 2026) : pas de glisser-déposer du film (chemin seulement) ; pas de reconnaissance « automatique » du diffuseur hors empreinte du PDF ; pas de profil « normes seules » ; pas de forme d'onde par piste ; pourcentage = images mesurées (lecture du fichier et mesures audio sans compteur) ; graphiques du rapport (PNG) au lieu de courbes dessinées dans la page ; une vignette par anomalie image, pas de bande de 5 images ; pas de colonne de référence dans les contrôles de format (source à ajouter aux `checks` plus tard) ; textes d'exemple de la maquette remplacés par les données réelles.

**Acceptation**
- Vincent produit un rapport sans ouvrir de terminal (à part `uv run pad-guard ui`). Test automatique : `uv run pytest -m e2e` (Chromium, fixture `bad_levels.mov`). Recette sur le vrai master Arte : à faire.

---

## Phase 6 : formats SDR étendus — faite (24-25 octobre 2026)

Décision de Damien (24 octobre 2026) : PAD Guard refuse seulement ce qu'il ne sait pas mesurer ; tout le reste est analysé, et un écart avec le profil du client est une anomalie de format, pas un refus.

**Livrables**
- `formats.py` : capacités de mesure, source unique des refus et du texte de l'écran de dépôt. Refusés : pas de décodeur, format de pixel hors liste, cadence variable ou hors liste, HDR / BT.2020 (Phase 7).
- Cadences 23,976 à 60 i/s ; timecode drop frame ; base du timecode lue dans le fichier (`tmcd`, TimecodeComponent MXF : ffprobe ne la donne pas) ; durées des règles en secondes (`merge_gap_seconds`, `min_event_seconds`, `duration_s`, `rules.params`), choix de regroupement dans `lumiris_maison` (A VERIFIER avec Vincent).
- Codecs ProRes (Proxy à 4444 XQ), DNxHD/DNxHR (LB à 444), XAVC/AVC-Intra/H.264, XDCAM HD422, HEVC, non compressé, DV ; conteneurs MOV, MP4, MXF OP1a et OP-Atom (vidéo seule).
- 8, 10 et 12 bits ; 4:2:0, 4:2:2, 4:4:4, R'G'B' ; alpha signalé ; plage pleine convertie, contenu plein-plage annoncé légal détecté.
- Toutes résolutions (SD à 4K DCI), pixels anamorphiques ; SD en BT.601 (coefficients usuels A VERIFIER : PDF à ajouter).
- Entrelacé : PSE trame par trame ; PsF. GOP long : erreur étendue à l'image clé suivante.
- Arte 1.2 : codecs du §3.2.2.2, 4:2:2 10 bits (§3.1), durées en secondes.
- Profil `lumiris_controle_technique` : « Rapport technique », sans verdict.
- Norme `normes/itu_bt709.yaml`.
- Performance : bandes adaptées à la largeur, 12 processus : UHD 25p à 1,4x le temps réel.

**Acceptation** : non-régression sur le vrai master Arte (événements identiques à l'image près, mesures identiques à l'octet après le nouveau décodeur), recette du 50p « destroyed » et d'ASTERIX (2K 23,976 DNxHR HQ 8 bits) ; tableau des formats dans `docs/PHASE6_RECETTE.md`.

**Reporté** : arte_uhd_sdr (via draft-profile) ; détection d'une inversion de l'ordre des trames ; audio des fichiers OP-Atom voisins ; séquences d'images (DPX, TIFF, EXR).

---

## Phase 7 : HDR

**Livrables**
- PQ et HLG (ITU-R BT.2100), conteneur BT.2020 ; luminance en cd/m² par image.
- MaxCLL / MaxFALL mesurés et comparés aux métadonnées ; métadonnées SMPTE ST 2086 ; gamut P3 dans BT.2020.
- Normes `normes/itu_bt2100.yaml` et `normes/itu_bt2408.yaml`.

**Acceptation**
- Recette obligatoire sur un vrai master HDR.

---

## Hors périmètre v3

- IMF (SMPTE ST 2067) et Dolby Vision, donc les livraisons Netflix.

---

## Décisions ouvertes à trancher avec Vincent

1. Mapping audio : VO / VF / VI en trois paires stéréo pour Arte (confirmé le 7 octobre 2026) ; à confirmer pour les autres chaînes.
2. Structure de tête précise par chaîne (durées de mire, de noir, présence d'un carton).
3. Liste des chaînes à couvrir en priorité (un profil chacune).
4. Faut-il un contrôle des films en 24 i/s natifs avant conversion 25 i/s ? (hors périmètre v2 si non.)
5. ~~Modèle local ou API externe~~ Tranché le 7 octobre 2026 : Ollama local uniquement.
