# Recette de la Phase 6 (25 octobre 2026)

Fichiers réels : code du commit `0b55d80` (sources figées) ; tableau des formats : code du commit `b641b3b` (refus HDR compris). Machine de développement (AMD Ryzen 9 5950X, 16 cœurs, Windows 11). Les fixtures sont générées par `tests/fixtures/make_fixtures.sh` ; chaque ligne est une analyse complète (`analyze`) avec le profil `lumiris_controle_technique` (aucun refus pour une raison de profil). « Lu » : ffprobe et PyAV ouvrent le fichier ; « Analysé » : mesures, structure, règles et rapport écrits.

## Fichiers réels

| Fichier | Profil | Lu | Analysé | Résultat | Durée |
|---|---|---|---|---|---|
| Master Arte 1080i50 ProRes HQ (120 Go, drapeau tb, images progressives) | `arte_hd_sdr` 1.2 | oui | oui | NON-CONFORME, 56 événements **identiques à l'image près** à ceux de la Phase 4a (seule la source de la règle des deux anomalies de niveaux change) ; audio identique à l'octet ; mesures vidéo identiques hors nouveaux champs de trame | 30 min (empreinte SHA-256 comprise) |
| 50p « destroyed » ProRes HQ 1080p50 (235 Go, TC base 50) | `arte_hd_sdr` 1.2 | oui | oui, 261 916 / 261 916 images, aucune erreur de décodage | NON-CONFORME : 217 bloquantes (loudness -0,4 LUFS, 215 dépassements de true peak, TC 00:00:00:00), 24 majeures, 80 mineures | 34 min |
| ASTERIX CLEO (DNxHR HQ 8 bits 2048x1556 23,976, TC base 24) | `arte_hd_sdr` 1.2 | oui | oui, 8 257 / 8 257 images | NON-CONFORME ; anomalies de format, pas de refus : cadence 24000/1001, 8 bits, 2048x1556, drapeau de balayage absent ; TC 00:00:00:00 | 3 min 49 |
| ASTERIX CLEO | `lumiris_controle_technique` | oui | oui | Rapport technique : 2 majeures (PSE), 3 mineures (images dupliquées), 33 informations (audio) | 2 min 11 |

## Formats (fixtures)

| Format testé | Fixture | Lu | Analysé | Refusé (motif) | Remarques |
|---|---|---|---|---|---|
| ProRes 422 HQ, MOV, 1080p25 | `ok_prores.mov` | oui | oui (code 0) | non | prores HQ, 1920x1080, 25/1, 4:2:2 10 bits ; 500/500 images, 0 erreur(s) ; anomalies : audio_loudness, audio_silence, freeze |
| ProRes 422 LT, MOV | `wrong_codec.mov` | oui | oui (code 0) | non | prores LT, 1920x1080, 25/1, 4:2:2 10 bits ; 500/500 images, 0 erreur(s) ; anomalies : audio_loudness, audio_silence, freeze |
| ProRes 4444 + alpha (12 bits 4:4:4), MOV | `fmt_prores4444_alpha.mov` | oui | oui (code 0) | non | prores 4444, 640x360, 25/1, 4:4:4 12 bits ; 50/50 images, 0 erreur(s) ; anomalies : alpha_channel, gamut |
| DNxHR HQX, MXF OP1a | `ok_dnxhr.mxf` | oui | oui (code 0) | non | dnxhd DNXHR HQX, 1920x1080, 25/1, 4:2:2 10 bits ; 500/500 images, 0 erreur(s) ; anomalies : audio_loudness, audio_silence, freeze |
| DNxHR HQX, MXF OP-Atom | `fmt_opatom.mxf` | oui | oui (code 0) | non | dnxhd DNXHR HQX, 320x180, 25/1, 4:2:2 10 bits ; 50/50 images, 0 erreur(s) ; anomalies : audio_not_analysed, gamut |
| DNxHR HQ 8 bits 2048x1556 23,976 (scan) | `fmt_dnxhr_hq_2k.mov` | oui | oui (code 0) | non | dnxhd DNXHR HQ, 2048x1556, 24000/1001, 4:2:2 8 bits ; 96/96 images, 0 erreur(s) ; anomalies : aucune |
| DNxHR 444 R'G'B', MOV | `fmt_dnxhr444_rgb.mov` | oui | oui (code 0) | non | dnxhd DNXHR 444, 640x360, 25/1, rgb 10 bits ; 50/50 images, 0 erreur(s) ; anomalies : format |
| XAVC / AVC-Intra (H.264 High 4:2:2 Intra 10 bits), MP4 | `fmt_h264_intra.mp4` | oui | oui (code 0) | non | h264 High 4:2:2 Intra, 1920x1080, 25/1, 4:2:2 10 bits ; 500/500 images, 0 erreur(s) ; anomalies : aucune |
| XDCAM HD422 (MPEG-2 4:2:2, GOP long), MXF | `xdcam_hd422.mxf` | oui | oui (code 0) | non | mpeg2video 4:2:2, 1920x1080, 25/1, 4:2:2 8 bits ; 100/100 images, 0 erreur(s) ; anomalies : aucune |
| H.264 4:2:0 8 bits GOP long, MP4 | `h264_lgop.mp4` | oui | oui (code 0) | non | h264 High, 1280x720, 25/1, 4:2:0 8 bits ; 100/100 images, 0 erreur(s) ; anomalies : aucune |
| HEVC Main 10 GOP long, MP4 | `hevc_lgop.mp4` | oui | oui (code 0) | non | hevc Main 10, 1280x720, 25/1, 4:2:0 10 bits ; 100/100 images, 0 erreur(s) ; anomalies : aucune |
| H.264 plage pleine (yuvj420p, pc), MP4 | `fmt_h264_full.mp4` | oui | oui (code 0) | non | h264 High, 640x360, 25/1, 4:2:0 8 bits ; 50/50 images, 0 erreur(s) ; anomalies : gamut |
| Contenu plein-plage annoncé légal, ProRes | `fmt_full_as_tv.mov` | oui | oui (code 0) | non | prores HQ, 640x360, 25/1, 4:2:2 10 bits ; 50/50 images, 0 erreur(s) ; anomalies : black_crush, gamut, range_content_mismatch, white_clip |
| Entrelacé 50i (flashs trame par trame), ProRes | `interlaced_flash.mov` | oui | oui (code 0) | non | prores HQ, 1920x1080, 25/1, 4:2:2 10 bits ; 100/100 images, 0 erreur(s) ; anomalies : pse |
| PsF (progressif marqué entrelacé), ProRes | `psf_prores.mov` | oui | oui (code 0) | non | prores HQ, 1920x1080, 25/1, 4:2:2 10 bits ; 100/100 images, 0 erreur(s) ; anomalies : aucune |
| 23,976p | `rate_23976.mov` | oui | oui (code 0) | non | prores HQ, 1920x1080, 24000/1001, 4:2:2 10 bits ; 480/480 images, 0 erreur(s) ; anomalies : aucune |
| 24p | `rate24_prores.mov` | oui | oui (code 0) | non | prores HQ, 1920x1080, 24/1, 4:2:2 10 bits ; 48/48 images, 0 erreur(s) ; anomalies : aucune |
| 29,97p drop frame | `rate_2997df.mov` | oui | oui (code 0) | non | prores HQ, 1920x1080, 30000/1001, 4:2:2 10 bits ; 600/600 images, 0 erreur(s) ; anomalies : aucune |
| 50p | `rate_50p.mov` | oui | oui (code 0) | non | prores HQ, 1920x1080, 50/1, 4:2:2 10 bits ; 1000/1000 images, 0 erreur(s) ; anomalies : aucune |
| 59,94p drop frame, MXF | `rate_5994df.mxf` | oui | oui (code 0) | non | dnxhd DNXHR HQX, 1920x1080, 60000/1001, 4:2:2 10 bits ; 1199/1199 images, 0 erreur(s) ; anomalies : aucune |
| UHD 3840x2160 2,39 | `fmt_uhd_239.mov` | oui | oui (code 0) | non | prores HQ, 3840x2160, 25/1, 4:2:2 10 bits ; 10/10 images, 0 erreur(s) ; anomalies : gamut |
| 4K DCI 4096x2160 24p | `fmt_dci4k.mov` | oui | oui (code 0) | non | prores HQ, 4096x2160, 24/1, 4:2:2 10 bits ; 11/11 images, 0 erreur(s) ; anomalies : gamut |
| SD PAL 16:9 anamorphique, BT.601 | `sd_pal_169.mov` | oui | oui (code 0) | non | prores HQ, 720x576, 25/1, 4:2:2 10 bits ; 50/50 images, 0 erreur(s) ; anomalies : format, gamut |
| DV PAL 4:2:0 | `sd_dv.mov` | oui | oui (code 0) | non | dvvideo , 720x576, 25/1, 4:2:0 8 bits ; 50/50 images, 0 erreur(s) ; anomalies : format, gamut |
| HDR PQ BT.2020 | `refuse_hdr_pq.mov` | oui | non | HDR ou BT.2020 (transfert smpte2084, primaires bt2020, matrice bt2020nc) : mesures prévues en Phase 7 (BT.2100), pas encore prises en charge. | |
| DV NTSC 4:1:1 | `refuse_dv_ntsc.mov` | oui | non | format de pixel yuv411p : PAD Guard ne sait mesurer que Y'CbCr 4:2:0, 4:2:2 ou 4:4:4, ou RVB, en 8, 10 ou 12 bits. | |
| Cadence variable, MP4 | `refuse_vfr.mp4` | oui | non | cadence variable (25/1 / 250/11) : les images ne sont pas régulièrement espacées, PAD Guard ne la mesure pas. | |
| 48 i/s | `refuse_48p.mov` | oui | non | cadence 48/1 (48 i/s) : PAD Guard ne sait mesurer que 24000/1001 (23,976 i/s) ou 24/1 (24 i/s) ou 25/1 (25 i/s) ou 30000/1001 (29,97 i/s) ou 30/1 (30 i/s) ou 50/1 (50 i/s) ou 60000/1001 (59,94 i/s) ou 60/1 (60 i/s). | |

Le DNxHR HQ d'ASTERIX n'est pas une anomalie de codec avec le profil Arte : « DNX HR/HQ » figure dans la liste du §3.2.2.2, marqué A VERIFIER (« 10bit » contradictoire, question à poser à Arte).

## Relecture du 25 octobre 2026

Sorties dans `C:\dev\pad-checker-recette\phase6fix\` (sources figées dans `src\`, même machine).

**1. Durée du master Arte (30 min contre 20 min en Phase 4a).** Les mesures par trame (`fu1`, `fd1`, `fu2`, `fd2`) étaient calculées pour tout fichier marqué entrelacé, donc pour ce master tb aux images progressives : +55 % de temps par image en 1080 (profilage : 53 ms contre 34 ms par image et par processus). Le balayage réel n'est connu qu'à la fin du décodage (part des images peignées sur tout le film), et un second décodage est exclu ; elles ne sont donc plus calculées que pour une image peignée (`comb` ≥ `comb_ratio_min`) ou qui suit une image peignée, ailleurs `null` (les deux trames montrent la même image : l'étape structure prend la différence entre images, puis aucune variation entre trames). Coût restant sur un master progressif : le rapport de peignage de l'image précédente (3 ms). Résultat : **12 min 48 s** au lieu de 30 min (empreinte SHA-256 comprise) ; 86 images sur 130 958 ont leurs mesures par trame ; colonnes hors trame et audio identiques à l'octet à la recette précédente, mesures par trame calculées identiques. Fixtures entrelacées (`interlaced_prores`, 250 images sur 500 sans mesure par trame ; `interlaced_flash` ; `psf_prores`) : événements identiques à l'image près.

**Vitesse UHD 25p** (ProRes 422 HQ 3840x2160, 60 s, 770 Mb/s, mire `testsrc2` bruitée, 2 pistes, analyse complète avec rapport) : 45,6 s, soit **1,32x le temps réel** (cible ≥ 1x atteinte).

**2. True peak du 50p « destroyed ».** Les événements audio étaient déjà fusionnés avec `merge_gap` (0,5 s), mais les dépassements de true peak sont espacés de 0,5 à 4 s. Nouveau paramètre maison `rules.audio_merge_gap_seconds` (3 s, la fenêtre du short term, EBU Tech 3341 §2.2 ; A VERIFIER avec Vincent) pour les événements audio ponctuels : true peak, excursion short term, double mono non identique. Chaque plage porte le nombre de dépassements (`occurrences`) et la valeur la plus forte (« 4,3 dBTP au maximum, 116 dépassements »). Sur le 50p (règles et rapport relancés sur les mesures de la recette) : 215 événements de true peak → **21** (774 dépassements), 71 excursions short term → 43 ; 321 événements → 99 (23 bloquants, 24 majeurs, 52 mineurs) ; verdict identique (NON-CONFORME, score 0).

**3. Anomalie « format » avec `lumiris_controle_technique`.** Elle vient des balises de colorimétrie, comparées aux valeurs BT.709 que le profil hérite de `itu_bt709` (la matrice sert aussi aux mesures, elle n'est pas « any ») : DV PAL, balises absentes (« non renseigné ») ; SD PAL ProRes, primaires et matrice `bt470bg` (BT.601) au lieu de `bt709` ; DNxHR 444 R'G'B', matrice `gbr` (pas de matrice, le cas normal d'un fichier RVB) au lieu de `bt709`. Gravité info dans les trois cas. Le type devient `format_color_tags` (« Balises de colorimétrie ») pour les primaires, le transfert, la matrice et la plage ; la gravité reste celle de `format` à défaut d'une chaîne propre.

**Non-régression du master Arte.** 56 événements aux mêmes images que la recette précédente et que la Phase 4a, même verdict (statut, score, compteurs, motifs). Différences : les deux balises de colorimétrie absentes sont de type `format_color_tags` au lieu de `format` ; une excursion short term qui regroupait déjà deux dépassements l'indique (« -15,2 LUFS au maximum, 2 dépassements ») ; avec la Phase 4a, la source de la règle des deux anomalies de niveaux, comme indiqué plus haut.

## Colorimétrie (25 octobre 2026)

Sorties dans `C:\dev\pad-checker-recette\phase6fix2\`.

**1. Matrice des mesures.** Les mesures (conversion RVB du gamut, conversion d'une source RVB ou plage pleine en Y'CbCr, mire de référence) utilisaient la matrice du profil (`format.color_space`, héritée de `itu_bt709` pour le contrôle technique) et non celle du fichier. Elles utilisent maintenant celle du fichier : sa balise si elle désigne une matrice prise en charge, sinon le standard de son nombre de lignes (576 → `bt470bg`, 480/486 → `smpte170m`, autre → `bt709`) ; une balise désignant une autre matrice (`smpte240m`…) est refusée. Le rapport indique l'origine (« matrice bt470bg (balise du fichier) »). Écart avant/après (profil `lumiris_controle_technique`) :

| Fixture | Matrice avant → après | Pixels hors gamut (max par image) | Niveaux Y |
|---|---|---|---|
| `sd_pal_169.mov` (balise `bt470bg`) | bt709 → bt470bg | 61,15 % → 1,50 % | identiques |
| `sd_dv.mov` (balise absente, 576 lignes) | bt709 → bt470bg | 62,16 % → 1,24 % | identiques |
| `fmt_dnxhr444_rgb.mov` (`gbr`, 360 lignes) | bt709 → bt709 | identiques | identiques |

Le DNxHR 444 RVB ne change pas : à 360 lignes, son standard est BT.709, comme le profil ; une source RVB SD serait désormais convertie en BT.601. Sur un fichier Y'CbCr, la matrice ne touche que le gamut (les niveaux Y sont lus directement).

**2. `lumiris_controle_technique`.** Primaires, transfert et matrice valent `coherent` : sont acceptés `gbr` pour la matrice d'une source RVB, `bt470bg` ou `smpte170m` (primaires et matrice) et `bt709` ou `smpte170m` (transfert, même courbe) pour la SD, `bt709` sinon. SD PAL et DNxHR 444 RVB : plus d'anomalie de format ; DV sans balises : trois `format_color_tags` en information, comme avant. Le profil Arte ne change pas.

**Non-régression du master Arte** (balise `bt709`) : 56 événements identiques à la relecture précédente, tous champs compris ; verdict identique ; mesures vidéo, audio et structure identiques à l'octet.

## Référence de non-régression du master Arte (31 octobre 2026)

**57 événements** (2 bloquants, 16 majeurs, 39 mineurs), NON-CONFORME, score 0, conservés dans
`tests/golden/arte_master/reference.json` (type, gravité et sa source, timecodes, textes de chaque événement ;
verdict ; SHA-256 du fichier). Elle remplace les 56 événements des relectures précédentes.

Le 57e vient du blanking à la ligne exacte (décision de Vincent, 31/10/2026) : « Format d'image », mineur
(Arte §3.2.4), « 808 lignes (lignes 136 à 943) × 1920 px : aucun format du profil ; le plus proche, 2.35, attend
lignes 132 à 947 (écart de 4 lignes) ». L'image est un 2.39 (808 lignes) ; l'ancien critère (99,9e centile)
lisait 816 lignes à partir de la ligne 128, à cause du débordement des blocs ProRes entrelacés (16 lignes
d'image) dans les lignes 128 à 135, qui sont noires (moyenne 64,1 ; au plus 8 pixels à 68-70). Les 56 autres
événements sont identiques, tous champs compris.

Contrôle, après toute modification des mesures, de la structure, des règles ou des profils :

```powershell
uv run pad-guard rerun <dossier du master> --from structure --profile profiles/arte_hd_sdr.yaml --no-thumbnails
uv run python tools/recette/non_regression.py compare <dossier du master>
$env:PAD_GUARD_ARTE_OUT = "<dossier du master>"; uv run pytest tests/test_non_regression_arte.py
```

Sans `--profile`, `rerun` garde le profil figé dans le dossier. Un écart voulu (décision) se fixe avec
`non_regression.py write <dossier>`, et le décompte de `tests/test_non_regression_arte.py` se met à jour.

