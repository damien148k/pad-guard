# Spécification fonctionnelle et technique — PAD Guard (v2)

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

Phase 6 (décision de Damien, 24 octobre 2026) : PAD Guard **refuse seulement ce qu'il ne sait pas mesurer** ; tout le reste est analysé, et un écart avec le profil du client (codec, résolution, cadence, profondeur…) est une anomalie du rapport (`format_codec`, `format_container`, `format_picture`, `format_resolution`, `format_frame_rate`, `format_color_tags` pour les balises de colorimétrie et de plage absentes ou différentes du profil, gravité du profil, à défaut celle de `format`), jamais un refus. La liste des capacités est dans `src/pad_guard/formats.py` (source unique des refus et du texte de l'écran de dépôt).

Mesuré :

| Caractéristique | Pris en charge |
|---|---|
| Codecs (décodeur FFmpeg de PyAV) | ProRes (Proxy à 4444 XQ), DNxHD / DNxHR (LB à 444), XAVC Intra / AVC-Intra / H.264, XDCAM HD422 (MPEG-2), HEVC, non compressé (v210, r210), DV |
| Conteneurs | MOV, MP4, MXF (OP1a, OP-Atom : vidéo seule, audio signalé « non analysé ») |
| Cadences | 23,976, 24, 25, 29,97, 30, 50, 59,94 et 60 i/s, fixes ; timecode drop frame et non drop frame |
| Balayage | progressif, entrelacé (trame haute ou basse en premier), PsF |
| Image | toute résolution (SD à 4K DCI), pixels carrés ou anamorphiques |
| Profondeur, échantillonnage | Y'CbCr 4:2:0, 4:2:2, 4:4:4 ou R'G'B', 8, 10 ou 12 bits ; canal alpha ignoré et signalé |
| Plage | légale ou pleine (convertie en plage légale avant la mesure) |
| Colorimétrie | SDR BT.709 ou BT.601 |

Refusé (code 2, motif nommé) : pas de décodeur, format de pixel hors de cette liste (4:1:1, Bayer, flottant…), cadence variable ou hors de la liste, HDR (PQ, HLG) ou BT.2020 (Phase 7). L'outil ne convertit jamais le fichier source.

Caractéristiques attendues : celles du profil (`format`), le profil `lumiris_controle_technique` n'en attendant aucune (`any`).

### 2.2 Audio

L'audio est lu **dans le conteneur**. Le profil définit le mapping attendu des pistes (ex. pistes 1-2 : stéréo VF, 3-4 : stéréo VI, 5-10 : 5.1).

**Numérotation des pistes :** une « piste » du profil est un **canal audio**, numéroté à partir de 1 dans l'ordre de tous les flux audio du conteneur. Un MOV avec un flux stéréo donne les pistes 1-2 ; un MXF avec six flux mono donne les pistes 1 à 6 ; un flux stéréo suivi de deux flux mono donne 1-2, 3, 4. `probe.json` enregistre la correspondance (index du flux, canal dans le flux) → numéro de piste. Un fichier WAV externe n'est pas pris en charge dans cette version.

### 2.3 Profil de chaîne

Un fichier YAML (voir `profiles/france_tv_hd.yaml`) décrivant toutes les règles applicables. Le schéma est défini en §6.

### 2.4 Options de ligne de commande

```
pad-guard analyze <fichier> --profile <yaml> --out <dossier>
    [--audio-map "VO:1-2,VF:3-4"]   groupes de pistes pour cette analyse (remplace audio.groups du profil)
    [--workers N]                   processus de mesure vidéo (défaut : automatique, sans effet sur les résultats)
    [--llm none|ollama]             défaut : none
    [--no-thumbnails]               sans vignettes (par défaut : une vignette par anomalie image)
    [--quick]                       aperçu rapide sans verdict (1 image sur 25)
pad-guard rerun <dossier>         relance structure, règles et rapport à partir des JSON, sans refaire les mesures
    [--from structure|rules|report] première étape relancée (défaut : structure)
    [--profile <yaml>]              autre profil ; refusé s'il change un paramètre de mesure
    [--no-thumbnails]
pad-guard report <dossier>        régénère le rapport à partir des JSON (= rerun --from report)
pad-guard validate-profile <yaml>
```

Codes de retour : 0 CONFORME, 4 NON-CONFORME (analyse menée à son terme), 1 usage ou profil incomplet, 2 fichier refusé.

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
| colorimétrie | `color_primaries`, `color_transfer`, `color_space` | `bt709` ×3 ; `unknown` = avertissement `minor` ; `coherent` : balises cohérentes avec le fichier (`gbr` pour une source RVB, BT.601 pour la SD, BT.709 sinon ; profil de contrôle technique) |
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
| `d_mean` | différence absolue moyenne de Y (non filtré) avec l'image précédente, en valeurs de code ; `null` pour la première image | images figées, dupliquées, mire |
| `d_up_pct`, `d_down_pct` | % de pixels dont la luminance relative a augmenté (diminué) de plus de `structure.pse.flash_min_delta_pct` depuis l'image précédente | PSE |

**Conversion RGB :** Y'CbCr 10 bits plage légale → R'G'B' avec la matrice inverse **du fichier** (décision de Damien, 25 octobre 2026 : sa balise `color_space` si elle désigne une matrice prise en charge, sinon le standard de son nombre de lignes : 576 → `bt470bg`, 480 ou 486 → `smpte170m`, autre → `bt709` ; une source RVB, balise `gbr`, est convertie en Y'CbCr avec ce standard ; une autre matrice, `smpte240m` par exemple, est refusée). La matrice du profil n'est qu'une balise attendue (`format_color_tags`), jamais un paramètre de mesure. en float32, sans clipping. Le résultat est comparé aux bornes du profil exprimées en % (-5 % à +105 % par défaut, EBU R103).

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

Le tableau `video` peut être volumineux (135 000 entrées pour 90 min) : il est **toujours** écrit en JSON Lines, au fil des mesures, dans `measurements_video.jsonl` (une ligne par image) ; les blocs audio de même dans `measurements_audio.jsonl` (une ligne par bloc de 100 ms et par groupe). `measurements.json` garde l'en-tête, l'intégrité, les seuils appliqués, la plage programme et les valeurs globales, et nomme ces deux fichiers. Un format unique évite deux chemins de lecture dans les étapes suivantes.

**Différences entre images (ajoutées en Phase 3, `schema_version` 2) :** les images figées, dupliquées et le PSE ont besoin de comparer chaque image à la précédente ; cette comparaison est faite pendant la passe de mesure (jamais par un second décodage). Luminance relative : réponse d'écran BT.1886 à noir nul, `((Y − 64) / 876)^2,4` bornée à [0, 1], comparée par tables d'entiers (exact). Un `measurements.json` de format 1 est refusé par les étapes suivantes : relancer `analyze`.

**Choix de mise en œuvre (Phase 2) :** loudness momentané, short term, intégré et LRA par FFmpeg `ebur128` (référence) ; true peak par l'interpolateur ×4 de l'UIT-R BS.1770-4 annexe 2 en NumPy, bloc par bloc, pour dater chaque pic (FFmpeg ne donne qu'un maximum cumulé à trois décimales linéaires) ; préfiltre vidéo : noyau binomial horizontal de `video.prefilter_taps` pixels (3 ou 5) ; chroma 4:2:2 interpolée linéairement pour la conversion RGB ; percentiles au rang le plus proche sur l'histogramme exact de Y.

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
- Format du timecode (Phase 6) : ffprobe donne le TC de départ dans la base de la piste timecode sans dire laquelle (un 50p dont la piste compte 25 images par seconde affiche `10:00:00:15` comme un 25p). La base, le drop frame et le nombre d'images par valeur de TC sont lus dans le fichier (`probe/tc_reader.py` : description de la piste `tmcd` en MOV/MP4, TimecodeComponent MXF) et écrits dans `probe.json` (`timecode_format`) ; à défaut, déduits de la cadence et signalés. Le TC s'affiche tel qu'il est stocké (base 50 : images 00 à 49) ; une base de moitié de la cadence donne une valeur pour deux images, suffixées `.1` et `.2` (`timecode.PAIR_SUFFIX`, en attendant la réponse de Vincent). Drop frame à 29,97 et 59,94 (SMPTE ST 12-1) ; les durées en secondes utilisent la vraie cadence, jamais la base du TC.

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

**Choix de mise en œuvre (Phase 3) :**
- Les détecteurs travaillent sur les colonnes de `measurements_video.jsonl` ; seules quelques images sont redécodées par accès direct (seek, exact sur ProRes et DNxHR qui sont intra) : l'image du milieu de chaque plan fixe d'au moins 1 s (candidat mire) et une image toutes les 10 s pour le format d'image. Le 1 kHz est lu sur 1 s au milieu de la mire.
- Mire : grille 12 × 16 de zones dont on garde le centre (marges de 20 %), moyenne Y, Cb, Cr comparée à la mire FFmpeg de référence (`pal75bars`, `pal100bars`, `smptehdbars`, convertie BT.709 plage légale) ; erreur = médiane des écarts par zone, pire des trois plans, comparée à `structure.bars.tolerance`. En mode `leaders: none` avec `bars.forbidden`, les trois mires sont cherchées. Une mire est un plan fixe : seule une mire immobile est reconnue.
- 1 kHz : fréquence dominante par FFT (fenêtre de Hann, tolérance 1 %), niveau = RMS + 3,01 dB (référence sinus pleine échelle = 0 dBFS), comparé à `structure.bars.tone_dbfs` ± `structure.bars.tone_tolerance_db`.
- Mode `classic` : le programme commence à la première image qui n'est ni mire ni noire ; le noir de tête est la plage noire et silencieuse qui la précède, le noir de queue la plage noire et silencieuse finale. Mode `none` : le programme est le fichier entier ; noirs de tête et de queue mesurés depuis le début et la fin.
- Images figées et dupliquées : `d_mean < structure.freeze.threshold` ; une suite de `n` images « identiques à la précédente » est une image tenue sur `n + 1` images. Les images noires et la mire sont exclues. Durée minimale : `structure.freeze.min_seconds` (au moins, bornes incluses).
- Noir isolé : une seule image noire entre deux images non noires, sauf si `y_mean` décroît strictement sur les 3 images qui précèdent (fin de fondu) ou croît strictement sur les 3 qui suivent (début de fondu).
- PSE : une transition est une image où plus de `flash_min_area_pct` % de l'image a éclairci (ou assombri) de plus de `flash_min_delta_pct` ; deux transitions de même sens sur des images consécutives n'en font qu'une ; `n` transitions dans une fenêtre d'une seconde font `n // 2` flashs.
- Fichier entrelacé : figées et dupliquées sont mesurées sur des images entières (deux trames) ; le PSE l'est trame par trame quand les images sont détectées entrelacées (Phase 6) : changement de luminance entre trames successives, la précédente interpolée sur les lignes de la suivante (« bob »), 50 transitions par seconde en 50i (champs `fu1`, `fd1`, `fu2`, `fd2`, pour un fichier marqué entrelacé). Ces champs ne sont calculés que pour une image peignée (`comb` ≥ `comb_ratio_min`) ou qui suit une image peignée (décision de Damien, 25 octobre 2026) ; ailleurs ils restent `null` : les deux trames montrent la même image, l'étape structure prend la différence entre images pour la première transition et aucune variation pour la seconde. Un master marqué entrelacé aux images progressives ne paie donc pas ces mesures (+55 % de temps par image en 1080). Le rapport l'indique.
- Format d'image : une ligne (colonne) est active si son 99,9e centile atteint `structure.black.y_max` (même critère que l'image noire). Seuls les nombres de lignes et de pixels actifs sont comparés au profil (la correspondance des numéros de ligne SMPTE reste à vérifier). Un format différent sur au moins 3 échantillons consécutifs est signalé en information.

---

## 7. Étape 4 : règles, événements, verdict

### 7.1 Agrégation en événements

Une anomalie par image devient un **événement** quand elle persiste. Règle d'agrégation :

- deux images en anomalie séparées de moins de `rules.merge_gap_seconds` (0,5 s dans `lumiris_maison`, convertie à la cadence du fichier, arrondie vers le bas : 12 images à 25 i/s, 25 à 50 i/s) appartiennent au même événement ; l'ancienne forme en images (`merge_gap_frames`) reste acceptée ;
- les événements audio ponctuels (true peak, excursion short term, double mono non identique) se regroupent de la même façon avec `rules.audio_merge_gap_seconds` (3 s dans `lumiris_maison`, la fenêtre du short term) : un événement par plage, avec le nombre de dépassements (`occurrences`) et la valeur la plus forte ; le verdict ne change pas (une plage bloquante reste bloquante) ;
- les durées des conditions de gravité s'écrivent en secondes (`duration_s`), les valeurs nommées dans `rules.params` (Phase 6 : une durée en images ne veut pas dire la même chose en 25 et en 50 i/s) ;
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

**Choix de mise en œuvre (Phase 3) :**
- Une image est en anomalie `white_clip` / `black_crush` / `gamut` quand `y_above_pct` / `y_below_pct` / `rgb_out_pct` atteint `video.max_out_of_range_area_pct` (Arte §3.2.3.3 : « au moins 1 % de la superficie »). La mire reconnue est exclue (une PLUGE est volontairement hors plage).
- Fusion : deux plages sont un même événement si moins de `merge_gap_frames` images propres les séparent. Durée minimale : `min_event_frames.<type>`, 1 (pas de filtre) si le type n'y figure pas.
- `worst_value` : `y_max` du pire pixel (blancs), `y_min` (noirs), surface (gamut), valeur en dB ou LUFS (audio) ; `area_pct_max` : surface maximale.
- Audio, sur la plage programme de `measurements.json` : loudness intégré, LRA, true peak et short term par groupe ; silence et phase par plages de blocs plus longues que `silence_max_seconds` / `phase_min_seconds` ; excursion short term : seule l'excursion au-dessus de la cible est contrôlée (le dialogue n'est pas détecté) ; un groupe dont toutes les pistes sont « sans contenu » ne produit pas en plus un événement de loudness ou de silence.
- Contrôles `probe` et `structure` en échec : un événement du `type` du contrôle ; balise de couleur absente : gravité `format.unknown_color_tags_severity`.
- Intégrité (`type: integrity`) : nombre d'images décodées différent de `nb_frames`, erreurs de décodage **dédoublonnées** (le message du décodeur et l'exception d'un même paquet ont la même clé ; un événement par erreur distincte avec le nombre d'images touchées), discontinuités de timestamp.
- Toutes les gravités possibles pour le profil et le fichier sont vérifiées avant de commencer (et avant les mesures dans `analyze`) : une gravité manquante fait refuser l'analyse.

---

## 8. Étape 5 : rapport

Fichier `rapport.md` puis `rapport.pdf`, en français, sections dans cet ordre :

1. **En-tête :** fichier, SHA-256, durée, profil utilisé (nom et version), version de l'outil, date d'analyse.
2. **Statut :** `CONFORME` ou `NON-CONFORME`, score, nombre d'événements par gravité.
3. **Synthèse.** Sans LLM : 3 à 6 phrases générées par gabarit à partir des compteurs. Avec LLM : 2 à 4 paragraphes rédigés par le modèle local à partir de `verdict.json` et de la liste des anomalies (jamais `measurements.json` brut), contrôlés par le code (§8.1).
4. **Contrôles de format et de structure :** tableau `contrôle / attendu / mesuré / OK`.
5. **Audio :** tableau par groupe de pistes (loudness, true peak, LRA, silences, phase).
6. **Tableaux chronologiques des anomalies** (deux tableaux : bloquantes et majeures, qui font le verdict ; puis « À vérifier » pour les mineures et les informations ; chaque ligne de détail cite la règle de gravité appliquée et sa source) : `TC début`, `TC fin`, `durée`, `type`, `valeur max`, `seuil`, `surface`, `gravité`, `qualification suggérée` (vide sans LLM), `vignette` (si `--thumbnails`).
7. **Annexe :** graphique de `y_p99` et `y_p01` dans le temps (matplotlib, PNG), graphique de loudness momentané, paramètres du profil appliqués.

**Choix de mise en œuvre (Phase 3) :** PDF produit localement par `markdown-it-py` (Markdown → HTML) et PyMuPDF (mise en page A4). WeasyPrint demande GTK sous Windows ; `markdown-pdf` dépend de `plantuml` (rendu par un serveur distant) et de `requests`, ce qui contredit le principe de confidentialité. Les vignettes (`--thumbnails`, dossier `vignettes/`) montrent l'image la plus mauvaise de chaque événement image ; pour les niveaux et le gamut, une deuxième moitié peint les pixels comptés par la mesure (même préfiltre, mêmes seuils). Les graphiques d'annexe sont dans `annexes/`. Une image n'est jamais réduite pour tenir en bas de page : chaque image, avec sa légende, passe entière à la page suivante si elle ne tient pas (décision du 23 octobre 2026) ; la légende du masque de pixels n'accompagne que les vignettes des anomalies de niveaux et de gamut. `run.json` garde la date et la ligne de commande de l'analyse et des relances ; `profile.yaml` est la copie du profil appliqué.

### 8.1 Couche IA (optionnelle, locale uniquement)

- Options `--llm none|ollama` (défaut `none`), `--llm-model`, `--llm-refresh` sur `analyze`, `rerun` et `report`. Avec `--llm none`, le rapport est identique à l'octet au rapport sans couche IA.
- Entrée : `verdict.json` (statut, libellé affiché, score, compteurs, motifs), le nom, la version et le statut du profil, les points clés de `probe.json` (codec, image, cadence, drapeau de balayage, balayage détecté, durée), les anomalies par type, et chaque événement tel que le rapport le montre (n°, type, gravité, TC, durée, valeur, seuil, surface, règle et source de la gravité, détail) ; les vignettes en image pour les événements qui en ont. Jamais les mesures image par image.
- Sortie (schéma JSON strict) : `synthese`, 2 à 4 paragraphes pour Vincent (ce qui bloque, ce qui est à corriger, ce qui est toléré, dans quel ordre s'en occuper) ; `qualifications`, pour chaque événement `blocking`, `major` ou `minor`, une valeur parmi « défaut à corriger », « choix artistique probable », « faux positif probable », « à vérifier à l'image », « à vérifier à l'écoute », avec une justification d'une phrase ; plusieurs événements d'une même famille peuvent être qualifiés par un seul élément (liste de numéros).
- Le modèle ne reçoit **jamais** de consigne qui lui permette de modifier le verdict. Le rapport affiche la qualification en italique comme suggestion à valider, la justification dans le détail de l'anomalie, et sous la synthèse : « Rédigée par IA locale (modèle, version du prompt) à partir des anomalies ci-dessous ; à relire. Le verdict est calculé par des règles. »
- **Contrôles déterministes** (`report/ai.py`) : tout nombre écrit en chiffres ou en lettres (valeurs, timecodes, compteurs, pourcentages) doit figurer dans les données fournies, à l'arrondi d'affichage près ; aucun timecode, numéro d'anomalie ou identifiant de type absent des données ; le verdict de `verdict.json` doit être écrit (NON-CONFORME, CONFORME, ou « sans anomalie bloquante » en indicatif) ; « conforme » est interdit si le verdict est NON-CONFORME ou indicatif ; « résultat indicatif » est obligatoire avec un profil `draft` ; aucun texte ne peut dire qu'une anomalie respecte son seuil. Une synthèse en échec est remplacée par le gabarit, avec un avertissement visible ; une qualification hors liste, non justifiée, contradictoire ou pour un événement inconnu laisse la case vide pour cette ligne seulement, avec le motif dans le détail.
- **Traçabilité et reproductibilité** : `llm_synthese.json` enregistre le modèle, les réglages, l'empreinte du prompt, des entrées (vignettes comprises) et de chaque requête, les réponses brutes et le résultat des contrôles. Tant que l'empreinte (prompt + entrées + modèle) est la même, `report` et `rerun --from report` rejouent ces réponses à travers les mêmes contrôles sans appeler le modèle ; `--llm-refresh` force un nouvel appel ; une passe interrompue (Ollama) n'est jamais rejouée. `events.json`, `verdict.json` et les fichiers de mesures ne changent jamais à cause de l'IA.
- **Implémentation : Ollama seulement**, via la bibliothèque Python `ollama` (`chat()` avec `images=[...]` et `format=<schéma JSON>` pour forcer une sortie structurée). Pas de connecteur vers une API externe : aucune donnée ne quitte la machine.
- **Modèle par défaut : `qwen3-vl:8b-instruct`** (Qwen3-VL 8B, vision + texte, multilingue, ≈ 6 Go), le même pour la synthèse et pour `draft-profile`, en CLI comme dans l'interface : une seule constante, `llm.DEFAULT_MODEL` (`llm/client.py`). Décision de Damien, 24 octobre 2026 : `qwen3-vl:32b-instruct` (≈ 20 Go) est trop lent sur la RTX 3080 Ti (délai de 600 s dépassé sur un lot de pages) ; il ne sert qu'en recette ponctuelle, choisi par `--llm-model` / `--model` ou dans l'interface. Pas de repli silencieux : si le modèle demandé n'est pas installé, le message dit « ollama pull <modèle> ». Le modèle n'est pas une valeur de profil : les champs `llm.model` et `llm.fallback_model`, jamais lus, ont été retirés du schéma et des profils le 25 octobre 2026 (sans changement de version : aucune mesure ni règle n'en dépendait) ; `rerun` sur un dossier d'analyse plus ancien les ignore après contrôle de l'empreinte.
- **Choix du modèle dans l'interface** : avant « Extraire » (brouillon) et, quand la synthèse IA est cochée, avant « Lancer l'analyse », la page affiche le modèle utilisé dans une liste des modèles installés (`ollama list`, `GET /api/llm/models`), le modèle par défaut présélectionné ; le choix est passé à la CLI (`--model`, `--llm-model`).
- **Délai dépassé** : chaque requête a 600 s. Au-delà, le message dit quoi faire : « modèle trop lent sur cette machine, choisir qwen3-vl:8b-instruct » (ou, si c'est déjà lui, fermer les programmes qui occupent la carte graphique).
- Une requête par événement qui a une vignette (vignette + JSON de l'événement), une par famille des autres événements (même type, groupe et gravité, ex. les silences VF), puis une requête finale pour la synthèse à partir des données et des qualifications retenues. Le contexte (`num_ctx`) est calculé une fois pour la passe sur la plus grosse demande, plus la réponse ; au-delà de 32 768 jetons, la couche IA n'est pas utilisée. Le modèle est libéré de la mémoire à la fin (`keep_alive` 0).
- Si Ollama ne répond pas, si le modèle n'est pas installé, ou si la réponse ne respecte pas le schéma après une relance : la synthèse par gabarit est utilisée, la colonne de qualification reste vide pour les événements concernés, et le rapport l'indique. Une erreur d'Ollama (injoignable, délai, refus) arrête la couche IA pour la passe. L'analyse ne doit jamais échouer à cause du LLM.
- Le prompt système est versionné dans `llm/prompts/` ; sa version figure dans le rapport.

---

## 9. Schéma du profil de chaîne (YAML)

Voir `profiles/france_tv_hd.yaml` pour l'exemple complet. Sections obligatoires :

```yaml
profile:        {name, version, broadcaster, source_document, notes}
format:         {codecs[], containers[], pix_fmt, width, height, fps_allowed[], field_order, color_*, color_range,
                 unknown_color_tags_severity, letterbox?}
video:          {bit_depth, y_min_legal, y_max_legal, y_tolerance_low_pct, y_tolerance_high_pct,
                 rgb_min_pct, rgb_max_pct, max_out_of_range_area_pct, prefilter, prefilter_taps (3|5, obligatoire si prefilter)}
audio:          {sample_rate, bit_depth, groups[],
                 loudness{long_program_min_seconds?, long{integrated_lufs, integrated_tolerance_lu, lra_max_lu?, ...},
                          short?{...}},   # sans "short", "long" s'applique à toutes les durées
                 true_peak_max_dbtp, silence_dbfs, silence_max_seconds, phase_min_correlation, exclude_head_tail}
structure:      {leaders: classic|none,
                 timecode{file_start, program_start, tolerance_frames},
                 bars{required, forbidden?, start_tc, min_seconds, pattern, tone_hz, tone_dbfs, tone_tolerance_db, tolerance},
                 black{head_min_seconds, tail_min_seconds (classic) | head_max_seconds, tail_max_seconds (none), y_max, silence_dbfs},
                 freeze{threshold, min_seconds}, pse{enabled, max_flashes_per_second}}
rules:          {merge_gap_frames, min_event_frames{...}, severity{...}, max_major, score_formula}
llm:            {backend: ollama, num_ctx, temperature, language}   # pas de modèle : llm.DEFAULT_MODEL, ou celui choisi au lancement
```

Chaque élément d'une chaîne de gravité porte sa `source` : un paragraphe du document du diffuseur (« Arte §3.2.3.3 »), une décision interne (« Lumiris : … ») ou « DEDUIT » quand aucun texte ne fixe la gravité. Une règle « DEDUIT » ne peut pas dépasser `minor` : le chargement du profil le refuse. `validate-profile` signale en avertissement les gravités bloquantes ou majeures dont la source est « A VERIFIER ».

`pad-guard validate-profile` vérifie le schéma avec pydantic et refuse tout champ inconnu (pour attraper les fautes de frappe). Les champs documentés comme « information » (ex. `av_sync_ms`, `credits`, `safe_areas`) sont acceptés et recopiés dans le rapport, mais ne produisent pas de règle tant que le moteur ne sait pas les mesurer.

Deux profils sont fournis : `profiles/arte_hd_sdr.yaml`, construit à partir des consignes officielles Arte V2 avec le paragraphe source cité pour chaque valeur (profil de référence), et `profiles/france_tv_hd.yaml`, un exemple à valider.

---

## 10. Exigences non fonctionnelles

- **Performance :** ≥ 2× temps réel en 1080p25 sur 16 cœurs. Mesurer avec `pad-guard analyze --benchmark`.
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

---

## 12. Normes et héritage (v3, Phase 4a)

### 12.1 Fichiers de normes

Le dossier `normes/` contient des fichiers YAML lisibles par l'outil (`ebu_r128.yaml`, `ebu_r103.yaml`, `lumiris_maison.yaml`…). Ils ont **le même schéma que les profils (§9), mais partiel** : seules les valeurs que le document fixe y figurent. Les PDF dont elles sont tirées sont dans `normes/sources/` (non versionné ; inventaire, versions et empreintes dans `normes/sources/README.md`).

```yaml
meta:
  kind: norm                      # obligatoire dans normes/
  name: ebu_r128                  # = nom du fichier sans extension
  document: {title: "EBU R 128 — Loudness normalisation…", version: "V5, novembre 2023"}
  source_pdf: normes/sources/AUDIO/r128.pdf
audio:
  true_peak_max_dbtp: -1.0
sources:                          # une source par valeur : document + paragraphe ou tableau
  audio.true_peak_max_dbtp: "EBU R 128 (2023), recommends m) : « … shall not exceed −1 dBTP … »"
```

- `sources` associe à un chemin pointé (`audio.true_peak_max_dbtp`) la citation exacte. Une entrée couvre aussi les valeurs situées sous ce chemin. Dans une norme, **toute valeur doit avoir une source** ; les chaînes de gravité (`rules.severity.*`) portent déjà la leur (`source:` de chaque règle).
- Une valeur que le document ne permet pas de fixer est absente, ou `null` avec le commentaire `# A VERIFIER : paragraphe à confirmer` ; elle n'est jamais déduite de mémoire.
- Une norme peut en étendre d'autres (`meta.extends`) et y renvoyer explicitement (`meta.refers_to`, avec la citation de sa page ; `cited_version` quand elle cite une autre version que celle de `normes/`). Aucune valeur n'est recopiée d'une norme à l'autre ; une valeur écrite par la norme l'emporte sur celles des normes qu'elle étend.
- `meta.applies` : `always` (défaut, normes internationales : proposées à tout nouveau brouillon de profil) ou `on_reference` (recommandation nationale comme CST-RT-040 : proposée seulement quand le document la cite).
- Une norme tirée de son PDF par `draft-profile --kind norme` porte aussi `source_pdf_sha256`, `validated_by` et `validated_at` (§13.4 bis).
- `lumiris_maison.yaml` regroupe les règles internes de Lumiris (gravités « Lumiris : … », contrôle PSE, paramètres de détection du balayage). Il a la forme d'une norme mais une priorité plus haute.

### 12.2 Profils : nouvelles métadonnées

La section d'en-tête du profil s'appelle désormais `meta:` (l'ancien nom `profile:` reste accepté pour les profils v2). Champs ajoutés :

| Champ | Rôle |
|---|---|
| `meta.extends` | liste de normes héritées (noms de fichiers de `normes/` sans extension), dans l'ordre d'application |
| `meta.status` | `draft` (défaut) ou `validated` |
| `meta.validated_by`, `meta.validated_at` | obligatoires si `status: validated` (date `AAAA-MM-JJ`) |
| `meta.source_pdf`, `meta.source_pdf_sha256` | cahier des charges du diffuseur dans `diffuseurs/` et son empreinte |

Un profil peut aussi porter une section `sources` (même forme que dans une norme) pour citer ses propres valeurs. Nouvelles valeurs du schéma : `format.delivery` (format attendu en livraison : `scan`, `fps`, `codec`), `video.scan_detection` (seuils de la détection de peignage) et `audio.loudness.method` (méthode de mesure, information).

### 12.3 Résolution du profil effectif

Résolution déterministe, sans IA :

1. Lire le profil et, récursivement, les normes de `meta.extends` dans `normes/` (dossier `normes/` voisin du dossier du profil s'il existe, sinon celui du dépôt). Une norme introuvable ou un cycle d'héritage fait refuser le profil.
2. Appliquer les couches dans l'ordre : normes dans l'ordre de `extends` (une norme héritée par une autre passe avant elle), puis `lumiris_maison` (obligatoirement le dernier de `extends` s'il est cité), puis le profil.
3. Fusion **champ par champ** : les dictionnaires sont fusionnés, toute autre valeur (nombre, texte, liste, chaîne de gravité) est remplacée en bloc par la couche suivante. Le dernier niveau gagne, y compris un `null` explicite.
4. Valider le résultat avec le schéma complet (§9). La règle « une valeur `null` dont dépend une règle fait refuser l'analyse » s'applique au profil effectif.
5. Lister les **conflits** : valeurs redéfinies avec une valeur différente (couche remplacée, couche gagnante, les deux valeurs).

`analyze` et `rerun` écrivent `effective_profile.json` dans le dossier de travail : couches appliquées (fichier, document, SHA-256 du fichier, fins de ligne normalisées), valeurs du profil effectif, origine de chaque valeur (fichier + source), conflits et empreinte. Clés triées, aucune date : même profil + mêmes normes = même fichier, à l'octet. L'**empreinte** est le SHA-256 des valeurs du profil effectif sérialisées de façon canonique ; elle est affichée dans le rapport avec le nom et le statut du profil, et `rerun` sans `--profile` réutilise ce profil effectif tel quel.

`pad-guard explain-profile <profil.yaml>` affiche chaque valeur, son origine et sa source, les couches et les conflits. `validate-profile` vérifie le schéma de chaque couche, l'existence des normes citées, l'absence de cycle et les sources des normes.

### 12.3 bis Le cahier des charges du client fait foi (décision du 23 octobre 2026)

Les normes informent et complètent ; elles ne remplacent jamais le document du client.

1. **Valeur fixée par le client** : appliquée telle quelle. Elle figure dans le profil du client avec sa citation, même si une norme dit la même chose. Si une norme diffère, l'annexe du rapport le signale en information (« Écarts entre le profil et les normes » : `video.y_tolerance_high_pct : ARTE G.E.I.E. 103,0 ; EBU R 103 105,0`), sans effet sur le verdict.
2. **Valeur absente chez le client mais donnée par une norme** : si le client renvoie explicitement à cette norme (`meta.refers_to`, confirmé à la relecture), c'est une exigence du client : la valeur garde son origine `normes/<norme>.yaml`, sa source devient « <citation du renvoi>, par renvoi à <norme> » (`referred_by` dans `effective_profile.json`) et elle n'est pas plafonnée ; une valeur chiffrée par le client l'emporte toujours. Le renvoi est **transitif** (décision de Damien, 25 octobre 2026) : quand la norme citée renvoie elle-même à d'autres normes (son `meta.refers_to`), leurs valeurs sont aussi des exigences du client, avec la source de toute la chaîne : « Annexe FTV p. 2 §I.A : « … », par renvoi à CST-RT-040, puis à EBU R 103 (CST-RT-040 V1.2, 2016 p. 5) (norme : …) ». Un renvoi direct du client à une norme passe avant le renvoi par une autre norme. `except: [chemins]` dans un renvoi exclut ces champs (et ce qui est dessous) du renvoi, sur toute la chaîne (« sauf le nombre de canaux audio ») : ils restent des recommandations plafonnées. Quand un renvoi cite une autre version que celle de `normes/` (`cited_version`), la version de `normes/` s'applique (« vérifier régulièrement qu'ils possèdent une version à jour », annexe France TV §I.A) et le rapport l'indique dans « Méthodes et limites » : « Version de norme : CST-RT-040 cite EBU R 103 v2.0 (juin 2016), version appliquée : version 3.0, mai 2020. » (`notes` de `effective_profile.json`, absent quand il n'y en a pas). Sinon, appliquée comme recommandation. Chaque anomalie déclare les valeurs du profil dont elle dépend (seuils, surface, plage légale, chaîne de gravité) ; si l'une d'elles vient d'une norme internationale (une couche `normes/` autre que `lumiris_maison`), la gravité est plafonnée à `minor` et la source de la règle devient « NORME (nom de la norme) : valeur absente du document du client… ». Une norme seule ne rend donc jamais un PAD NON-CONFORME. Les règles maison gardent leur gravité.
3. **Méthode de mesure non précisée par le client** (préfiltre, fenêtres, gating) : suivre la norme plutôt qu'un choix maison.
4. **« A VERIFIER »** signifie uniquement : valeur sans citation du document du client. Un écart avec une norme n'en est jamais un motif.

### 12.4 Statut du profil

Un profil `draft` peut servir, mais le rapport porte en tête « PROFIL NON VALIDÉ — résultat indicatif » et n'affiche jamais CONFORME : le statut devient « INDICATIF : sans anomalie bloquante » ou « INDICATIF : NON-CONFORME » (le verdict calculé par les règles est inchangé dans `verdict.json`, qui porte `indicative: true`).

### 12.5 Cadence, balayage et livraison

- Cadence : `probe.json` donne `r_frame_rate` et `avg_frame_rate` (fractions exactes). Depuis la Phase 6, les cadences 23,976 à 60 i/s sont mesurées (`formats.MEASURABLE_RATES`) ; une cadence variable ou hors de cette liste fait refuser le fichier (code 2) avec un message qui la nomme.
- Balayage : `field_order` vient de `probe.json` ; la passe de mesure calcule pour chaque image un indicateur de peignage `comb` = moyenne de |Y(l) − Y(l+1)| (lignes voisines, trames opposées) divisée par la moyenne de |Y(l) − Y(l+2)| (lignes de même trame). Une image en mouvement (`d_mean` ≥ `video.scan_detection.motion_min`) est « peignée » si `comb` ≥ `comb_ratio_min`. Selon la part d'images peignées parmi les images en mouvement, `scan_detected` vaut `interlaced`, `progressive` ou `undetermined` (moins de `min_moving_frames` images en mouvement, ou part intermédiaire). Un avertissement est émis si le drapeau `field_order` et la détection ne concordent pas.
- Règle de balayage (`rules/scan.py`, décision du 24 octobre 2026) : c'est le balayage détecté qui décide, pas le drapeau seul. Avec un profil progressif (`format.field_order: progressive`) et une détection déterminée : images progressives sous un drapeau entrelacé → `scan_flag_mismatch` (« Drapeau de balayage incorrect (tb) sur un master progressif : corriger l'étiquette à l'export », règle Lumiris `major` de `normes/lumiris_maison.yaml`) ; images entrelacées → `scan_interlaced`, de gravité fixée par le profil (Arte : `minor`, §3.2.2.1, 1080i50 accepté jusqu'au 31/12/2027). Aucune règle ne lit la date du jour (reproductibilité) : c'est une nouvelle version du profil qui change la gravité. Dans les autres cas (profil entrelacé, détection indéterminée, drapeau absent), le contrôle du drapeau `field_order` de `probe.json` (type `format`) s'applique tel quel. La ligne « Balayage » du tableau « Contrôles de format » montre le balayage détecté et le drapeau.
- Livraison : le balayage du master (détecté, sinon le drapeau) et sa cadence sont comparés à `format.delivery`. S'ils diffèrent, la section « Livraison » du rapport l'explique et un événement `delivery_conversion_required` est émis, de gravité `info` (règle `rules.severity.delivery_conversion_required`) : ce n'est pas une non-conformité du master. Le codec de livraison est rappelé dans la section mais ne déclenche pas l'événement (le master ProRes ou DNxHR est toujours transcodé par le prestataire).

---

## 12 bis. Formats (Phase 6)

- **Profondeur.** Un fichier 8 bits est converti en 10 bits (x 4) avant toute comparaison ; un fichier 12 bits est mesuré en 12 bits, avec les seuils 10 bits multipliés par 4 exactement (décision de Damien, 24 octobre 2026), et ses valeurs écrites en codes 10 bits au quart près.
- **Échantillonnage.** 4:2:2 : chroma interpolée linéairement sur les colonnes impaires ; 4:2:0 : chaque ligne de chroma couvre les deux lignes de luminance ; 4:4:4 : sans interpolation.
- **Plage et RVB.** Un fichier en plage pleine (balise `pc`, `yuvj*`) ou en R'G'B' est converti en Y'CbCr plage légale (codes 12 bits) avant la mesure, d'après BT.2100-3 tableau 9 et BT.709-6 §3.2 à 3.4 : les seuils du profil, exprimés sur la plage légale, s'appliquent aux bons niveaux. Un fichier annoncé en plage légale dont au moins 1 % des images atteignent les bornes 4 ou 1019 (BT.709-6 §4.7 ; ProRes et DNxHR écrêtent à 4-1019) a un contenu en plage pleine probable : `range_content_mismatch` (règle maison, A VERIFIER). Une balise plage pleine dont le contenu reste dans 64-940 : `range_tag_suspect` (info).
- **Matrices.** BT.709 (`bt709`) et BT.601 (`bt470bg`, `smpte170m`, coefficients usuels A VERIFIER tant que le PDF manque) ; la mire de référence est générée dans la matrice du fichier (celle des mesures).
- **Alpha.** Le plan alpha est ignoré, signalé (`alpha_channel`, info).
- **Format d'image.** Rapport largeur / hauteur de la zone active avec le rapport des pixels (`sample_aspect_ratio`) ; un profil sans tableau de formats (`formats: []`) relève la zone active sans comparer.
- **GOP long.** Le décodeur relève les images clés ; une erreur de décodage couvre les images jusqu'à l'image clé suivante. L'accès direct (vignettes, mire, format d'image) part de l'image clé précédente : exact, vérifié sur MPEG-2, H.264 et HEVC.
- **MXF OP-Atom.** Vidéo seule : l'audio, dans d'autres fichiers, n'est pas analysé (`audio_not_analysed`, info) au lieu de pistes manquantes.
- **PsF.** `format.field_order: psf` : des images progressives marquées entrelacées sont conformes ; des images entrelacées restent `scan_interlaced`.
- **Performance.** Chaque image est mesurée par bandes d'environ 61 000 pixels, 12 processus : UHD 25p à 1,4x le temps réel (README).

### 12 ter. Profil « contrôle technique Lumiris »

`profiles/lumiris_controle_technique.yaml` (`meta.purpose: technical`) : fichiers de travail sans diffuseur. Les valeurs de comparaison du format et le TC de départ valent `any` (tout accepté, explicitement : jamais par une valeur absente), les amorces `unchecked`. Niveaux EBU R 103 et loudness EBU R 128 en recommandation (plafonnés à mineur), règles maison avec leur gravité. Le rapport, la CLI (code 0), l'interface et la synthèse IA affichent « Rapport technique », jamais CONFORME ni NON-CONFORME.

## 13. `draft-profile`, `review-profile`, `compare-profiles` (v3, Phase 4b)

### 13.1 Extraction (`pad-guard draft-profile <pdf> --name <nom> [--model …]`)

- **Lecture du PDF** (`draft/pdf.py`) : texte de chaque page et tableaux (`pdfplumber`, lignes « cellule | cellule ») ; les pages qui contiennent un tableau ou moins de 200 caractères sont rendues en image (`pypdfium2`, environ 90 dpi) pour le modèle de vision. Le PDF n'est jamais modifié ; son SHA-256 est enregistré.
- **Modèle** (`llm/`) : interface `LLMClient` (une consigne, un schéma JSON imposé, des images facultatives, un délai) et sa seule implémentation `OllamaClient` (bibliothèque `ollama`, `format` = schéma, température 0, graine fixe). Modèle par défaut `llm.DEFAULT_MODEL` = `qwen3-vl:8b-instruct` (voir §8.1), `--model` pour un autre modèle installé. Consigne système versionnée : `llm/prompts/draft_profile_v2.md` (v1 gardée pour la traçabilité des anciens brouillons).
- **Schéma** (`draft/schema.py`) : généré depuis le modèle pydantic du profil. La réponse est une liste `findings` d'objets `{field, source_type, value, page, quote, unit, norm}` ; `source_type` distingue `client_value` (le document du client écrit la valeur), `client_refers_to_norm` (le document renvoie à une norme sans chiffre, ex. « conforme à la R128 » : `value` null, `norm` la nomme ; le modèle ne recopie jamais une valeur de norme qu'il connaîtrait) et `not_found` (ignoré) ; `field` est une énumération des chemins de toutes les feuilles des sections `format`, `video`, `audio`, `structure` (106 champs) : le modèle ne peut pas répondre sur un champ qui n'existe pas. La consigne liste chaque champ avec son type et sa description française (tirée du modèle). `meta` (fixé par l'outil), `rules` (gravités, décidées par l'humain) et `llm` ne sont pas extraits.
- **Contexte** (`num_ctx`) : Ollama charge un modèle avec 4096 jetons de contexte si on ne lui en donne pas, alors qu'une demande de draft-profile fait de 4000 à 9200 jetons (mesuré sur Arte et France TV, images comprises) et une réponse jusqu'à 8000. La taille est donc fixée pour toute l'extraction (la changer recharge le modèle et change la sortie), calculée avant la première requête : plus grosse demande estimée (0,33 jeton par caractère + 2000 par image, au-dessus de toutes les mesures) + 10240 jetons de réponse, arrondie au multiple de 1024 supérieur (Arte 22528, France TV 19456) ; `--num-ctx` la force. Un contexte trop petit est refusé avant toute requête. Ollama refuse une demande plus longue que le contexte (il ne la tronque pas) ; ce refus, une réponse coupée en fin de contexte (`done_reason: length`) et une génération interrompue pour répétition arrêtent l'extraction avec un message clair, sans brouillon écrit. Chaque ligne du `.llm.jsonl` enregistre `num_ctx`, `prompt_tokens` et `output_tokens`. À la fin (succès ou échec), le modèle est libéré de la mémoire (`keep_alive: 0`).
- **Limite et boucles** : le schéma impose au plus 40 propositions par réponse (`maxItems`), ce qui oblige un modèle qui se répète en boucle à fermer la liste (qwen3-vl:8b sur Arte p. 89-90 : 16339 jetons de la même proposition sans limite). Un lot qui atteint la limite est redemandé page par page ; une page seule qui l'atteint encore est signalée en tête du brouillon, dans `findings.json` (`capped_pages`) et dans review-profile : « page N : limite atteinte, propositions possiblement manquantes ». `repeat_penalty` est une option (`--repeat-penalty`) ; sans elle, Ollama applique 1,0 (aucune pénalité, mesuré).
- **Traçabilité** : chaque ligne du `.llm.jsonl` porte les réglages envoyés (`options`), `max_findings`, `system_sha256` (consigne), `glossary_sha256` (fichier du glossaire, fins de ligne LF) et `prompt_sha256` (consigne, demande, schéma et images de la requête) : deux recettes dont les empreintes diffèrent n'ont pas reçu les mêmes demandes. `tools/recette/banc.py` compare plusieurs modèles avec une consigne, un glossaire, des exemples et un contexte figés.
- **Lots** : deux pages par requête (au plus deux images). La détection de la table des matières n'est pas faite.
- **Glossaire** (`normes/glossaire.yaml`, `draft/glossary.py`, relu par un humain ; ce n'est pas une norme) : pour chaque champ extractible, termes français et anglais, unités acceptées, contextes à distinguer (programme long / court / bande-annonce / direct ; VO / VF ; HD / UHD), plage vraisemblable et forme (timecode, cadence) ; et les alias des normes (« R128 », « R 128 »…). Les champs dont un terme figure dans les pages du lot ont leur entrée de glossaire dans la demande.
- **Exemples** (`draft/examples.py`) : pour ces mêmes champs, au plus deux citations tirées des profils `profiles/*.yaml` en `status: validated` (« chez tel diffuseur, cette phrase a donné ce champ »). Les profils du diffuseur du PDF lu ne sont jamais utilisés : même SHA-256 ou même nom de PDF, ou même premier mot du diffuseur ou du nom de profil (« ARTE G.E.I.E. », `arte_uhd`). Les notes maison (« Lumiris : … ») ne sont pas des exemples.

### 13.2 Contrôle déterministe de chaque valeur

Une valeur n'est retenue (statut `A_VERIFIER`, à confirmer par un humain) que si :

1. elle est du type du champ (sinon `VALEUR_INVALIDE`) ;
2. le champ n'est pas un paramètre interne de PAD Guard ou du master Lumiris (`draft/vocabulary.py`, `INTERNAL` : seuils de détection, codecs du master…) ;
3. la page citée fait partie du lot et a une couche texte (sinon `CITATION_NON_VERIFIABLE`) ;
4. la citation fait au plus 300 caractères et se retrouve dans le texte de la page citée, après normalisation (formes de compatibilité Unicode donc ligatures et espaces insécables, apostrophes et guillemets typographiques, tirets et signe moins, césures en fin de ligne, espaces, casse) ; à défaut, pour une page à tableau, tous les mots de la citation se suivent dans l'ordre à l'intérieur d'une même ligne du tableau (le modèle peut omettre une cellule) ;
5. la citation contient le vocabulaire du champ (accents et casse ignorés : `KEYWORDS`, par exemple « silence » pour `audio.silence_dbfs`) ;
6. pour un choix ou un oui/non, la citation en porte le sens (`EVIDENCE` : `leaders: none` exige une négation portant sur les amorces, `classic` l'exclut ; une interdiction vraie exige une négation ; `progressive` exige « progressif »…) ; un texte libre (`LITERAL_TEXT`, ex. `format.delivery.codec`) doit figurer tel quel dans la citation ;
7. chaque nombre de la valeur figure dans la citation (virgule ou point décimal, signe moins typographique, « 2’00 » = 120 s, « 48 kHz » = 48000, milliers « 1.000 ») et est suivi de l'unité attendue (dBFS, LUFS, LU, dBTP, %, Hz, ms, bits, paires ; pour une liste, l'unité peut être partagée : « 24 ou 16 bits ») ;
8. pour les valeurs de loudness des programmes longs ou courts, la dernière durée citée avant le passage dans la page correspond ; dans un tableau, c'est l'en-tête de la colonne de la cellule qui porte la valeur.

Le vocabulaire (point 5) est aussi reconnu par un terme du glossaire. Une valeur qui passe ces contrôles est ensuite confrontée au glossaire : hors de la plage vraisemblable, unité citée par le modèle non acceptée pour le champ (« dBTP max » commence par « dBTP » et passe ; « dB » ne couvre jamais « dBFS »), timecode mal formé → `INVRAISEMBLABLE` : la valeur est gardée dans le brouillon, signalée en commentaire et en rouge à la relecture, jamais acceptée par défaut.

Un renvoi à une norme (`client_refers_to_norm`) n'apporte aucune valeur (une valeur proposée est ignorée) : la citation doit se trouver dans la page et nommer une norme (alias du glossaire, sinon le nom donné par le modèle doit figurer dans la citation). Le champ est `RENVOI_NORME`, absent du brouillon (hérité de la norme), et la norme est proposée dans `meta.extends` ; c'est la relecture qui confirme le renvoi (§13.4).

Sinon `CITATION_INVALIDE`, avec la raison. Un champ dont toutes les propositions échouent est écrit `null` (le profil refusera de tourner tant qu'un humain ne l'a pas tranché).

**Fusion** : deux valeurs contrôlées différentes pour un même champ (une valeur `INVRAISEMBLABLE` compte) (une liste de valeurs simples est comparée comme un ensemble), ou une même citation et un même nombre donnés pour deux champs différents, donnent `CONFLIT` : toutes les propositions sont gardées, le champ est `null`, un humain tranche. Jamais de choix silencieux.

### 13.3 Brouillon

Dans `profiles/drafts/` : `<nom>.yaml` (meta `status: draft`, `source_pdf`, `source_pdf_sha256`, `extends` proposé = toutes les normes de `normes/` (`meta.kind: norm`), celles que le document cite après les autres (elles priment), `lumiris_maison` en dernier ; en tête, les normes citées (page, citation ; une norme du glossaire sans fichier est signalée « absente de normes/ ») et les champs `RENVOI_NORME` ; chaque valeur suivie de `# A VERIFIER (p. N) « citation »` ; champs en conflit ou invalides à `null` avec les propositions en commentaire ; liste des champs non trouvés en tête), `<nom>.findings.json` (toutes les propositions et leur statut) et `<nom>.llm.jsonl` (réponses brutes du modèle, une ligne par lot). Les trois fichiers sont écrits ensemble à la fin : une réponse mal formée ou un délai dépassé arrête tout, sans fichier à moitié écrit. Le brouillon est partiel : il n'est pas analysable tel quel.

### 13.4 Relecture (`pad-guard review-profile <brouillon.yaml> [--base …] [--out …]`)

Par défaut, seuls les champs à vérifier (`A_VERIFIER`), `INVRAISEMBLABLE` (en rouge, défaut : garder la valeur de base ou laisser vide), `RENVOI_NORME` (le renvoi est montré ; laissé vide, le champ est hérité de la norme) et en conflit sont présentés (`--tous` : aussi ceux dont toutes les propositions ont été rejetées, qui sinon gardent la valeur du profil de base) ; Entrée choisit la réponse par défaut (accepter, sinon garder la valeur de base, sinon laisser vide). Pour chaque champ : description, valeur proposée (ou propositions en conflit), page et citation, valeur du profil de base et valeur des normes (information). L'humain accepte, choisit une proposition, corrige (valeur, page et citation facultatives), garde la valeur de base ou laisse vide (le champ est alors hérité d'une norme, donc plafonné à mineur). Les réponses sont gardées dans `<nom>.review.json`. Après une correction ou une valeur complétée, l'outil demande le terme employé par le document et, après confirmation (terme français ou anglais), l'ajoute au glossaire (`normes/` à côté du profil de base) : le diffuseur suivant est mieux reconnu. Un terme déjà reconnu n'est pas ajouté ; le glossaire reste à relire par un humain.

Les valeurs que le PDF n'a pas données viennent du **profil de base** : `profiles/<nom>.yaml` s'il existe, sinon le gabarit `profiles/modeles/gabarit_diffuseur.yaml` (gravités toutes `minor` tant qu'un humain ne les a pas fixées) ; elles sont marquées `A VERIFIER : sans citation` dans le profil écrit. Les valeurs retenues sont citées dans la section `sources`.

Après les champs, chaque norme de `normes/` à laquelle le document renvoie est présentée (page, citation, valeurs de la norme) : confirmée, elle est écrite dans `meta.refers_to` avec la citation du renvoi, et ses valeurs que le client ne chiffre pas deviennent des exigences du client, sans plafonnement ; non confirmée (défaut), elles restent des recommandations plafonnées à mineur. Les renvois confirmés sont aussi gardés dans `<nom>.review.json`.

Avant d'écrire, le profil est résolu : pour chaque champ obligatoire encore manquant (une section acceptée en partie, comme `format.delivery` réduit au codec), la valeur est demandée, ou la section entière est retirée ; tant que le profil est invalide, rien n'est écrit. Puis la liste, en rouge, des **règles bloquantes ou majeures dont une valeur ne viendrait que d'une norme sans renvoi du client** (elles seraient plafonnées à mineur) ; il faut confirmer pour continuer. Enfin le nom du validateur : le profil est écrit dans `profiles/<nom>.yaml` avec `status: validated`, `validated_by`, `validated_at`.

### 13.4 bis Brouillon de norme (`draft-profile <pdf> --kind norme --name <nom> --title … --doc-version …`)

Décision de Damien, 25 octobre 2026 : une norme absente de `normes/` (ex. CST-RT-040, à laquelle renvoie l'annexe France TV) se tire de son PDF comme un profil. Même extraction, même consigne (`draft_profile_v2`), mêmes contrôles des citations et du glossaire. Le brouillon va dans `normes/drafts/<nom>.yaml` (avec `.findings.json` et `.llm.jsonl`) : hors du motif `normes/*.yaml`, il n'est jamais hérité par un profil. Son `meta` : `kind: norm`, `document {title, version}` (obligatoires à la ligne de commande), `source_pdf` et son empreinte, et dans `extends` les seules normes de `normes/` que le document cite.

`review-profile normes/drafts/<nom>.yaml` reconnaît une norme :
- pas de profil de base (`--base` refusé), pas de champs obligatoires à compléter, pas de `rules` ni de `llm` : une valeur refusée ou laissée vide est absente de la norme ;
- une correction cite toujours la page et la citation exacte du document ;
- chaque renvoi à une norme de `normes/` est confirmé ou non : confirmé, il va dans `extends` et `refers_to` de la norme, avec la version citée si elle diffère ; non confirmé, la norme n'est pas étendue ;
- dernière question : proposer la norme à tout nouveau brouillon de profil (`applies: always`) ou seulement quand le document la cite (`on_reference`, défaut) ;
- la norme est vérifiée (schéma, une source par valeur, normes étendues présentes, pas de cycle) puis écrite dans `normes/<nom>.yaml` avec `validated_by` et `validated_at`. Chaque source est « <titre court> <version> p. N : « citation » ».

### 13.5 Comparaison (`pad-guard compare-profiles <a.yaml> <b.yaml> [--all]`)

Deux profils fusionnés avec leurs normes (un brouillon incomplet est accepté), comparés valeur par valeur : identique, différent, seulement dans A, seulement dans B, avec l'origine de chaque valeur et, pour un brouillon, son statut d'extraction.

Critère d'acceptation : sur le PDF Arte V2, toute valeur proposée a une citation vérifiée, et la comparaison automatique avec `profiles/arte_hd_sdr.yaml` ne montre aucune valeur fausse non signalée.
