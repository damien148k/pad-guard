# Spécification fonctionnelle et technique — pad-checker (v2)

Système d'analyse automatisée et de contrôle qualité PAD, Lumiris Production.
Version 2 du 7 octobre 2026. Remplace le cahier des charges v1 (sources DPX/CRI abandonnées).

---

## 1. Contexte et objectif

Lumiris Production restaure des films et livre des masters aux diffuseurs. Chaque master doit respecter le cahier des charges technique du diffuseur (France Télévisions, Arte, Canal+, plateformes). Aujourd'hui, cette vérification se fait par visionnage linéaire et lecture au moniteur forme d'onde.

**Objectif :** un outil qui prend un fichier master, un profil de chaîne, et produit en une passe :
1. un fichier de mesures complet et reproductible ;
2. une liste d'anomalies agrégées en événements, avec gravité ;
3. un verdict CONFORME / NON-CONFORME calculé par des règles ;
4. un rapport lisible (Markdown et PDF), avec une synthèse rédigée.

**Ce que l'outil n'est pas :** un outil de certification. Il remplace le pré-contrôle interne, pas le contrôle du diffuseur. En particulier, le test épilepsie (PSE) est une approximation, pas un test Harding certifié.

---

## 2. Entrées

### 2.1 Fichiers vidéo acceptés

| Codec | Conteneur | Profondeur | Sous-échantillonnage | `pix_fmt` FFmpeg attendu |
|---|---|---|---|---|
| Apple ProRes 422 HQ | `.mov` | 10 bits | 4:2:2 | `yuv422p10le` |
| Avid DNxHR HQX | `.mxf` (OP1a) ou `.mov` | 10 bits | 4:2:2 | `yuv422p10le` |

Tout autre codec, profil (ex. ProRes 422 LT, DNxHR HQ 8 bits) ou `pix_fmt` est **refusé** avec un message explicite. L'outil ne convertit jamais le fichier.

Caractéristiques attendues par défaut (modifiables par le profil) : 1920×1080, 25 i/s progressif, Rec. 709, plage légale (`color_range=tv`), audio PCM 24 bits 48 kHz.

### 2.2 Audio

L'audio est lu **dans le conteneur**. Le profil définit le mapping attendu des pistes (ex. pistes 1-2 : stéréo VF, 3-4 : stéréo VI, 5-10 : 5.1).

**Numérotation des pistes :** une « piste » du profil est un **canal audio**, numéroté à partir de 1 dans l'ordre de tous les flux audio du conteneur. Un MOV avec un flux stéréo donne les pistes 1-2 ; un MXF avec six flux mono donne les pistes 1 à 6 ; un flux stéréo suivi de deux flux mono donne 1-2, 3, 4. `probe.json` enregistre la correspondance (index du flux, canal dans le flux) → numéro de piste. Un fichier WAV externe n'est pas pris en charge dans cette version.

### 2.3 Profil de chaîne

Un fichier YAML (voir `profiles/france_tv_hd.yaml`) décrivant toutes les règles applicables. Le schéma est défini en §6.

### 2.4 Options de ligne de commande

```
pad-checker analyze <fichier> --profile <yaml> --out <dossier>
    [--llm none|ollama]             défaut : none
    [--thumbnails]                  extraire une vignette par événement
    [--quick]                       aperçu rapide sans verdict (1 image sur 25)
pad-checker report <dossier>        régénère le rapport à partir des JSON
pad-checker validate-profile <yaml>
```

---

## 3. Architecture en pipeline

```
fichier.mov
   │
   ▼
[1] probe        ffprobe -> probe.json          (métadonnées, pistes, TC de départ)
   │
   ▼
[2] measure      PyAV + NumPy -> measurements.json   (une entrée par image + blocs audio)
   │
   ▼
[3] structure    -> structure.json              (mire, noirs, décompte, TC, figés, PSE)
   │
   ▼
[4] rules        profil YAML -> events.json + verdict.json
   │
   ▼
[5] report       Jinja2 -> rapport.md, rapport.pdf   (+ synthèse LLM optionnelle)
```

Chaque étape lit le JSON de la précédente et écrit le sien dans `--out`. Toute étape peut être relancée seule. Les JSON sont versionnés (`"schema_version"`) et contiennent la version de l'outil.

---

## 4. Étape 1 : probe (métadonnées)

Source : `ffprobe -v error -show_format -show_streams -show_entries ... -of json`.

Extraire et vérifier contre le profil :

| Champ | Source ffprobe | Règle typique |
|---|---|---|
| codec, profil | `codec_name`, `profile` | doit être dans la liste autorisée |
| `pix_fmt` | `pix_fmt` | `yuv422p10le` |
| résolution | `width`, `height` | 1920×1080 |
| cadence | `r_frame_rate`, `avg_frame_rate` | dans `format.fps_allowed` (Arte : 25/1 ou 50/1), et les deux doivent être égales |
| balayage | `field_order` | `progressive` |
| colorimétrie | `color_primaries`, `color_transfer`, `color_space` | `bt709` ×3 ; `unknown` = avertissement `minor` |
| plage | `color_range` | `tv` |
| durée | `duration`, `nb_frames` | cohérence entre les deux ; durée totale vs. durée annoncée dans le profil (tolérance) |
| timecode de départ | tag `timecode` (piste `tmcd` en MOV, `timecode` en MXF) | égal à `profile.structure.timecode.file_start` |
| audio | par piste : `codec_name`, `sample_rate`, `bits_per_raw_sample`, `channels` | selon mapping du profil |
| intégrité | pendant la passe de mesure (§5.1), pas de décodage séparé | zéro erreur de décodage PyAV, et images décodées = `nb_frames` |

Sortie : `probe.json` avec les valeurs brutes, la table des pistes audio et, pour chaque règle, `expected` / `actual` / `ok`.

L'intégrité n'est pas vérifiée par `probe` : elle demanderait un second décodage complet (doublement du temps d'analyse). Le décodeur de l'étape 2 compte les images décodées et collecte les erreurs PyAV ; le résultat (`integrity`) est écrit dans `measurements.json` et vérifié par `rules`. En Phase 1, `analyze --benchmark` fait ce contrôle sur la passe de décodage.

---

## 5. Étape 2 : mesures par image

### 5.1 Décodage

PyAV, `thread_type="AUTO"`, sans conversion de format : on travaille directement sur les plans Y, Cb, Cr en `uint16` (valeurs 0–1023). Le décodage ProRes/DNxHR est CPU uniquement (NVDEC ne gère pas ces codecs).

Le décodeur fait aussi le **contrôle d'intégrité** : toute erreur PyAV est consignée (numéro d'image, message) au lieu d'interrompre l'analyse, et le nombre d'images décodées est comparé à `nb_frames`.

Objectif de performance : **au moins 2× temps réel** en 1080p25 sur un processeur 16 cœurs (un film de 90 min analysé en moins de 45 min), mesuré et noté dans le README.

### 5.2 Mesures luminance et chrominance (par image)

Calculées en NumPy sur le plan Y, puis sur Cb et Cr, puis sur une conversion RGB :

| Mesure | Définition | Usage |
|---|---|---|
| `y_min`, `y_max` | extrêmes de Y | information |
| `y_p01`, `y_p99` | percentiles 0,1 % et 99,9 % de Y | robustes au grain |
| `y_mean` | moyenne de Y | détection de noir, PSE |
| `y_below_pct` | % de pixels avec Y sous la borne basse **tolérée** (`y_tolerance_low_pct`, 55 en 10 bits pour -1 %) | règle noirs écrasés |
| `y_above_pct` | % de pixels avec Y au-dessus de la borne haute **tolérée** (`y_tolerance_high_pct`, 967 pour 103 %) | règle blancs clippés |
| `y_below_legal_pct`, `y_above_legal_pct` | % de pixels avec Y < `video.y_min_legal` (64) ou > `video.y_max_legal` (940) | information, aucune règle |
| `rgb_out_pct` | % de pixels dont R, G ou B est hors `[rgb_min, rgb_max]` après conversion BT.709 (plage légale) | règle gamut |
| `cb_min`, `cb_max`, `cr_min`, `cr_max` | extrêmes de chroma | information |
| `sat_max` | saturation max (`sqrt(Cb²+Cr²)` centré) | information |

**Conversion RGB :** Y'CbCr 10 bits plage légale → R'G'B' avec la matrice BT.709 inverse, en float32, sans clipping. Le résultat est comparé aux bornes du profil exprimées en % (-5 % à +105 % par défaut, EBU R103).

**Conversion des pourcentages en valeurs de code :** `code = y_min_legal + pct/100 × (y_max_legal − y_min_legal)`, arrondi vers l'extérieur (borne basse vers le bas, borne haute vers le haut) ; la plage obtenue est inclusive. Exemple : -1 % → 55,24 → 55 ; 103 % → 966,28 → 967.

**Seuils par défaut (EBU R103, 10 bits) :** Y légal entre 64 et 940 ; tolérance -1 % / +103 % soit `[55, 967]` ; RGB entre -5 % et +105 % soit `[20, 984]` ; **surface tolérée : 1 % des pixels par image**. Ces valeurs vivent dans le profil, pas dans le code.

Optionnel : filtrage passe-bas horizontal (noyau 3 ou 5 pixels) avant mesure, comme le recommande R103, activable par le profil (`video.prefilter: true`).

### 5.3 Mesures audio (par bloc de 100 ms et globales)

Via `ffmpeg -af ebur128=peak=true:metadata=1,ametadata=print` ou via `pyloudnorm` sur les échantillons décodés (choisir l'un des deux et le justifier ; FFmpeg est la référence).

| Mesure | Portée | Règle typique (France, CST RT-017) |
|---|---|---|
| loudness intégré (LUFS) | programme entier, gating EBU | -23 ±1 LU |
| true peak max (dBTP) | programme | ≤ -3 dBTP |
| LRA (LU) | programme | ≤ 20 LU (si le profil l'exige) |
| loudness momentané (400 ms) | blocs | détection de plages silencieuses et de pics |
| silence | plages avec niveau < -60 dBFS pendant > N s | `major` hors tête/queue |
| phase stéréo | corrélation < -0,3 sur > N s | `minor` ou `major` selon profil |
| clics / saturation numérique | échantillons consécutifs à 0 dBFS | `major` |

| loudness short term (3 s) | fenêtre glissante | excursion max autour de la cible (Arte : ±7 LU sur le dialogue, programmes > 2 min) ; plafond absolu pour les programmes courts (Arte : ≤ -20 LUFS) |
| piste sans contenu | par piste, programme entier | piste entière < `audio.silent_track_dbfs` → `audio_silent_track` (Arte l'interdit : `blocking`) |
| double mono | par paire déclarée mono | les deux pistes doivent être identiques à l'échantillon près et en phase → `audio_dual_mono_mismatch` |
| quantification | par piste | `bits_per_raw_sample` dans `audio.bit_depth_allowed`, et identique sur toutes les pistes |

Appliquer les mesures **à chaque groupe de pistes** du mapping (VF, VI, 5.1 séparément). Si `audio.exclude_head_tail` est vrai, exclure la tête et la queue (le 1 kHz de mire n'est pas du programme) ; pour les chaînes sans amorce (Arte), tout le fichier est du programme. Le profil choisit le jeu de règles `loudness.long` ou `loudness.short` selon la durée du programme et `loudness.long_program_min_seconds`.

### 5.4 Fichier `measurements.json`

```json
{
  "schema_version": 1,
  "tool_version": "0.3.0",
  "source": {"path": "...", "sha256": "...", "frames": 135000, "fps": 25},
  "video": [
    {"f": 0, "y_min": 64, "y_max": 940, "y_p01": 66, "y_p99": 912, "y_mean": 302.1,
     "y_below_pct": 0.0, "y_above_pct": 0.0, "y_below_legal_pct": 0.0, "y_above_legal_pct": 0.0,
     "rgb_out_pct": 0.0, "sat_max": 311}
  ],
  "audio": {
    "groups": {"VF": {"integrated_lufs": -23.2, "true_peak_dbtp": -3.4, "lra_lu": 11.0,
                       "blocks": [{"t": 0.0, "m_lufs": -70.0, "tp": -80.0}]}}
  }
}
```

Le tableau `video` peut être volumineux (135 000 entrées pour 90 min) : écrire en JSON Lines (`measurements.jsonl`) si la taille dépasse 50 Mo, et noter le format dans l'en-tête.

---

## 6. Étape 3 : structure du fichier

Toutes les positions attendues viennent de `profile.structure`. Deux cas selon la chaîne :

- `structure.leaders: classic` : le fichier commence par une tête (mire, noir, décompte) et finit par une queue de noir. Exemple ci-dessous.
- `structure.leaders: none` : **aucune amorce** ; la première image du fichier est la première image du programme, au TC `10:00:00:00`, et le fichier se termine sur la dernière image du programme. C'est le cas d'**Arte** (« Le programme ne doit pas contenir d'amorces de début et de fin », consignes V2 §3.2.2.1). Dans ce mode, deux anomalies distinctes :
  - une mire en tête (ou ailleurs) → `structure_bars_present` (`blocking` chez Arte) ;
  - plus de `structure.black.head_max_seconds` de noir en tête, ou plus de `structure.black.tail_max_seconds` de noir en queue → `structure_black_too_long` (`minor` chez Arte : un fondu au noir est légitime, un noir d'amorce ne l'est pas).

Exemple de tête PAD classique (mode `classic`) :

```
09:59:30:00  mire de barres + 1 kHz à -18 dBFS      (30 s)
09:59:50:00  carton d'identification (optionnel)
09:59:55:00  noir et silence                          (5 s, avec décompte éventuel)
10:00:00:00  début du programme
...
fin programme  noir et silence de queue               (≥ 10 s selon chaîne)
```

### 6.1 Détection de la mire

Comparer chaque image de la plage attendue à une mire de référence générée par FFmpeg (`smptehdbars` ou `ebu` 75 %/100 %) : erreur absolue moyenne sur Y, Cb, Cr par colonne de barre < seuil (`structure.bars.tolerance`). Reconnaître aussi la mire par ses moyennes de colonnes si la référence exacte diffère (texte incrusté, logo). Vérifier le 1 kHz : fréquence dominante par FFT sur 1 s et niveau RMS vs. `structure.bars.tone_dbfs` (±0,5 dB).

### 6.2 Noirs et silences

Noir : `y_p99 < structure.black.y_max` (défaut 68, soit 1 % au-dessus de 64) et audio momentané < `structure.black.silence_dbfs`. Mesurer durée des noirs de tête et de queue et les comparer aux minimums du profil.

### 6.3 Timecode

- TC de départ du fichier = `structure.timecode.file_start`.
- Première image non noire après la tête = `structure.timecode.program_start` (10:00:00:00), tolérance ± `structure.timecode.tolerance_frames`.
- Continuité : aucun saut de TC (vérifié par cohérence `nb_frames` ↔ durée ; les conteneurs MOV/MXF ne portent qu'un TC de départ).
- Drop frame interdit en 25 i/s.

### 6.4 Images figées, noires isolées, dupliquées

- Figée : différence absolue moyenne entre images consécutives < `structure.freeze.threshold` pendant > `structure.freeze.min_seconds`, hors plages de noir attendues. Gravité `major`.
- Noir isolé : image noire (critère §6.2) entourée d'images non noires, hors fondu (un fondu a un `y_mean` qui décroît de façon monotone sur plusieurs images). Gravité `major`.
- Image dupliquée : différence quasi nulle sur exactement 1 image au milieu d'un mouvement. Gravité `minor` (fréquent en conversion de cadence).

### 6.5 Format d'image et bandes noires (letterbox / pillarbox)

Si `format.letterbox.check` est vrai : sur un échantillon d'images réparties sur tout le programme (ex. 1 image toutes les 10 s, hors noir), mesurer les bandes noires haut/bas et gauche/droite (lignes et colonnes dont `y_p99 < structure.black.y_max`). En déduire le format d'image dominant et le comparer au tableau `format.letterbox.formats` du profil (Arte §3.2.4 : 1.85 → 1036 lignes actives, 2.35 → 816 lignes actives, positions précises imposées). Écart > `tolerance_lines` → anomalie `letterbox` (`minor` par défaut). Un changement de format en cours de programme est signalé en `info`.

### 6.6 PSE (risque d'épilepsie photosensible), version simplifiée

Inspiré d'ITU-R BT.1702 et des lignes directrices Ofcom, sans prétendre les remplacer :
- Un **flash** = une paire de variations opposées de `y_mean` (converti en luminance relative) de plus de 20 cd/m² (≈ 10 % de la plage) entre images consécutives ou proches, sur plus de 25 % de la surface de l'image.
- **Alerte** si plus de 3 flashs dans n'importe quelle fenêtre de 1 seconde. Gravité `major`, et texte dans le rapport : « à vérifier avec un analyseur Harding certifié ».
- Détection de motifs réguliers (rayures) : hors périmètre v2.

Sortie : `structure.json` avec, pour chaque contrôle, `expected`, `actual`, `ok`, et les plages d'images concernées.

---

## 7. Étape 4 : règles, événements, verdict

### 7.1 Agrégation en événements

Une anomalie par image devient un **événement** quand elle persiste. Règle d'agrégation :

- deux images en anomalie séparées de moins de `rules.merge_gap_frames` (défaut 12, soit 0,5 s) appartiennent au même événement ;
- un événement de durée inférieure à `rules.min_event_frames` (défaut 1 pour les blancs clippés, car un flash d'une image compte ; défaut 3 pour le gamut) est ignoré, sauf si le profil dit le contraire ;
- un événement porte : `type`, `frame_start`, `frame_end`, `tc_start`, `tc_end`, `duration_frames`, `worst_value`, `worst_frame`, `threshold`, `severity`, `area_pct_max`.

### 7.2 Gravité

Définie par le profil, par type d'anomalie, en fonction de la valeur et de la durée. Exemple pour `white_clip` :

```yaml
white_clip:
  severity:
    - {if: "worst_value > 1004 or area_pct_max > 5", then: blocking}
    - {if: "duration_frames >= 25", then: major}
    - {else: minor}
```

Le moteur de règles évalue ces expressions avec un évaluateur **sécurisé** (pas de `eval` Python : utiliser `simpleeval` ou un mini-parseur) sur les champs de l'événement.

### 7.3 Verdict et score

- `NON-CONFORME` si au moins un événement `blocking`, ou si le nombre d'événements `major` dépasse `rules.max_major` (défaut 0), ou si un contrôle `probe` / `structure` marqué `required` échoue.
- `CONFORME` sinon, avec la liste des `minor`.
- **Score** (0–100, informatif) : `100 - 40·blocking - 10·major - 2·minor`, borné à 0. Formule dans le profil, modifiable.

Sortie : `events.json` (liste d'événements) et `verdict.json` (statut, score, compteurs, liste des contrôles requis échoués).

---

## 8. Étape 5 : rapport

Fichier `rapport.md` puis `rapport.pdf`, en français, sections dans cet ordre :

1. **En-tête :** fichier, SHA-256, durée, profil utilisé (nom et version), version de l'outil, date d'analyse.
2. **Statut :** `CONFORME` ou `NON-CONFORME`, score, nombre d'événements par gravité.
3. **Synthèse** (3 à 6 phrases). Sans LLM : texte généré par gabarit à partir des compteurs. Avec LLM : texte rédigé par le modèle à partir de `verdict.json` + `events.json` agrégé (jamais `measurements.json` brut).
4. **Contrôles de format et de structure :** tableau `contrôle / attendu / mesuré / OK`.
5. **Audio :** tableau par groupe de pistes (loudness, true peak, LRA, silences, phase).
6. **Tableau chronologique des anomalies :** `TC début`, `TC fin`, `durée`, `type`, `valeur max`, `seuil`, `surface`, `gravité`, `qualification suggérée` (vide sans LLM), `vignette` (si `--thumbnails`).
7. **Annexe :** graphique de `y_p99` et `y_p01` dans le temps (matplotlib, PNG), graphique de loudness momentané, paramètres du profil appliqués.

### 8.1 Couche IA (optionnelle, locale uniquement)

- Entrée : `verdict.json`, `events.json`, le nom de la chaîne, et pour les événements vidéo les vignettes (`--thumbnails`) en image.
- Sortie attendue (schéma JSON strict) : `summary` (texte en français, 3 à 6 phrases), et pour chaque événement `suggested_qualification` ∈ {`defect`, `probably_artistic`, `unsure`} + `reason` (une phrase).
- Le modèle ne reçoit **jamais** de consigne qui lui permette de modifier le verdict. Le rapport affiche la qualification comme « suggestion à valider ».
- **Implémentation : Ollama seulement**, via la bibliothèque Python `ollama` (`chat()` avec `images=[...]` et `format=<schéma JSON>` pour forcer une sortie structurée). Pas de connecteur vers une API externe : aucune donnée ne quitte la machine.
- **Modèle par défaut : `qwen3-vl:32b-instruct`** (Qwen3-VL 32B, vision + texte, multilingue, quantifié Q4_K_M ≈ 20 Go). Il tient dans les 24 Go d'une RTX 4090 à condition de limiter le contexte (`num_ctx` 8192) et de ne pas faire tourner autre chose sur le GPU pendant l'appel. **Modèle de repli : `qwen3-vl:8b-instruct`** (≈ 6 Go, 3 à 4 fois plus rapide, légèrement moins précis), sélectionnable par `--llm-model`. Les deux noms sont dans le profil (`llm.model`, `llm.fallback_model`), jamais codés en dur.
- Un seul événement par requête (vignette + JSON de l'événement), puis une requête finale pour la synthèse à partir de `verdict.json` et de la liste des qualifications. Cela borne la taille du contexte et permet de reprendre après une interruption.
- Si Ollama ne répond pas, si le modèle n'est pas installé, ou si la réponse ne respecte pas le schéma après une relance : la synthèse par gabarit est utilisée, la colonne de qualification reste vide, et le rapport l'indique. L'analyse ne doit jamais échouer à cause du LLM.
- Le prompt système est versionné dans `llm/prompts/` ; sa version figure dans le rapport.

---

## 9. Schéma du profil de chaîne (YAML)

Voir `profiles/france_tv_hd.yaml` pour l'exemple complet. Sections obligatoires :

```yaml
profile:        {name, version, broadcaster, source_document, notes}
format:         {codecs[], containers[], pix_fmt, width, height, fps_allowed[], field_order, color_*, color_range,
                 unknown_color_tags_severity, letterbox?}
video:          {bit_depth, y_min_legal, y_max_legal, y_tolerance_low_pct, y_tolerance_high_pct,
                 rgb_min_pct, rgb_max_pct, max_out_of_range_area_pct, prefilter}
audio:          {sample_rate, bit_depth, groups[],
                 loudness{long_program_min_seconds?, long{integrated_lufs, integrated_tolerance_lu, lra_max_lu?, ...},
                          short?{...}},   # sans "short", "long" s'applique à toutes les durées
                 true_peak_max_dbtp, silence_dbfs, silence_max_seconds, phase_min_correlation, exclude_head_tail}
structure:      {leaders: classic|none,
                 timecode{file_start, program_start, tolerance_frames},
                 bars{required, start_tc, min_seconds, pattern, tone_hz, tone_dbfs, tolerance},
                 black{head_min_seconds, tail_min_seconds, y_max, silence_dbfs},
                 freeze{threshold, min_seconds}, pse{enabled, max_flashes_per_second}}
rules:          {merge_gap_frames, min_event_frames{...}, severity{...}, max_major, score_formula}
llm:            {backend: ollama, model, fallback_model, num_ctx, temperature, language}
```

`pad-checker validate-profile` vérifie le schéma avec pydantic et refuse tout champ inconnu (pour attraper les fautes de frappe). Les champs documentés comme « information » (ex. `av_sync_ms`, `credits`, `safe_areas`) sont acceptés et recopiés dans le rapport, mais ne produisent pas de règle tant que le moteur ne sait pas les mesurer.

Deux profils sont fournis : `profiles/arte_hd_sdr.yaml`, construit à partir des consignes officielles Arte V2 avec le paragraphe source cité pour chaque valeur (profil de référence), et `profiles/france_tv_hd.yaml`, un exemple à valider.

---

## 10. Exigences non fonctionnelles

- **Performance :** ≥ 2× temps réel en 1080p25 sur 16 cœurs. Mesurer avec `pad-checker analyze --benchmark`.
- **Mémoire :** < 4 Go quelle que soit la durée du film (traitement en flux).
- **Reproductibilité :** test automatisé qui analyse deux fois la même fixture et compare les JSON.
- **Robustesse :** fichier tronqué, piste audio manquante, TC absent → erreur claire, code de retour non nul, rapport partiel si possible.
- **Traçabilité :** chaque rapport contient la version de l'outil, du profil, le SHA-256 du fichier source et la ligne de commande utilisée.
- **Hors ligne par défaut.**
- **Journalisation :** `--verbose` affiche la progression par étape avec `rich`.

---

## 11. Hors périmètre (v2)

- HDR / UHD / Rec. 2020 (profils HLG/PQ) : prévu v3, l'architecture doit le permettre (seuils dans le profil, conversion RGB paramétrée par les primaires).
- Sous-titres, zones de sécurité des titres.
- Conversion ou correction du fichier.
- Fichiers audio externes (WAV).
- Interface web (Phase 5 de la feuille de route, après validation de la CLI).
