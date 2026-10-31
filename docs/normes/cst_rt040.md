# CST-RT-040 — Rec Tech PAD Fichiers Editeurs (TV) (V1.2, 2016) : relevé des valeurs

> **Comment relire** (la signature ne porte que sur ce tableau)
>
> 1. Pour chaque ligne, ouvrir le PDF de la norme (dossier `normes\sources\`) à la page indiquée et comparer la valeur à la citation.
> 2. Dans la colonne « OK / correction », écrire `OK`, ou noter la correction (valeur juste, page, citation).
> 3. Un champ absent du tableau n'est pas contrôlé par cette norme.
> 4. Une correction se fait par `releve-norme` (ligne modifiée avec sa citation), puis nouvelle relecture.
> 5. Signer : `uv run pad-guard signer-norme cst_rt040 --par "Vincent"` (refusé si la norme a changé depuis ce tableau).

Document : `normes/sources/TV/cst-rt-040-tv-2016-pad_fichiers_editeurs_v1.2.pdf` (SHA-256 `c3c2a86b10aed7c7b068b5b775d9f17366ebedfcfe619316f6dd793a78480b3c`).
Relevé par Claude Code (décision de Damien du 28/10/2026 : relevé sans questionnaire) le 28/10/2026 : `normes/releves/cst_rt040.yaml`.
Norme écrite à partir de ce relevé : `normes/cst_rt040.yaml`.
Empreinte de `normes/cst_rt040.yaml` à la génération de ce tableau : `280090e14bb729cb6c3da7b976f944ef5983266b90a71c12e168d08ceba8a694`.

Chaque citation a été retrouvée par `pad-guard releve-norme` dans la page indiquée ; pour une valeur chiffrée, le nombre est dans la citation, et dans un tableau la colonne correspond au champ. Le code ne juge pas du sens : c'est l'objet de cette relecture.

## Normes auxquelles ce document renvoie

Leurs valeurs s'appliquent aussi quand un diffuseur renvoie à ce document (renvoi transitif) ; elles ne sont pas recopiées ici.

| Norme | Citation du renvoi | Version citée | OK / correction |
|---|---|---|---|
| `ebu_r128` | CST-RT-040 V1.2, 2016 p. 4 : « EBU-R128 et R128s1: normalisation de l’intensité sonore (ou sonie, ou loudness) et niveau maximum permis » |  | |
| `ebu_r128_s1` | CST-RT-040 V1.2, 2016 p. 4 : « EBU-R128 et R128s1: normalisation de l’intensité sonore (ou sonie, ou loudness) et niveau maximum permis » |  | |
| `itu_bt709` | CST-RT-040 V1.2, 2016 p. 4 : « ITU-R BT.709 : Paramètres de codage vidéo HD » |  | |
| `ebu_r103` | CST-RT-040 V1.2, 2016 p. 5 : « Conformément à la recommandation EBU R 103 (v2.0 juin 2016), et afin de garantir le respect de l’espace » | v2.0 (juin 2016) | |

## Valeurs

| Champ | Valeur | Page | Citation | Remarque | OK / correction |
|---|---|---|---|---|---|
| `format.width`<br>Largeur de l'image en pixels (ex. 1920) | `1920` | 4 | « SMPTE 274M : Paramètres signal HD 1920x1080 » | Référence à SMPTE 274M ; la phrase qui suit (« Le signal vidéo correspond aux caractéristiques 1080i […] de ces normes ») en fait une exigence. | |
| `format.height`<br>Hauteur de l'image en lignes (ex. 1080) | `1080` | 4 | « SMPTE 274M : Paramètres signal HD 1920x1080 » | Même citation que la largeur. | |
| `format.fps_allowed`<br>Cadences d'images acceptées, en fractions 'num/den' (ex. '25/1', '50/1') | `["25/1"]` | 4 | « Le signal vidéo correspond aux caractéristiques 1080i (entrelacé) à 25 images/seconde » | Aussi p. 5 (« 1080i – 25 images/seconde - 4:2:2 - ratio image 16/9 »). Le balayage entrelacé n'a pas de valeur ici : voir « sans valeur » (ordre des trames non écrit). | |
| `format.chroma_allowed`<br>Sous-échantillonnage de la chrominance accepté : 4:2:0, 4:2:2, 4:4:4, ou rgb (fichier RVB) | `["4:2:2"]` | 5 | « 1080i – 25 images/seconde - 4:2:2 - ratio image 16/9 » | « Sauf mention contraire de la part de l’éditeur » (p. 5) : standard de fabrication du PAD. | |
| `format.bit_depth_allowed`<br>Profondeurs d'image acceptées en bits par composante (ex. 10) | `[8]` | 6 | « lors de la conformation du signal vidéo 8 bits destiné au fichier Prêt A Diffuser » | Seule mention de la profondeur du PAD (cohérente avec AS-10 « High_HD_2014 », p. 15, non lu ici). Un master Lumiris en 10 bits serait signalé pour un diffuseur qui renvoie à RT 040 sans écrire sa propre profondeur. | |
| `format.color_range`<br>Plage de codage : tv (légale, 64-940 en 10 bits) ou pc (pleine) | `tv` | 5 | « 10 bits 64 – 940 20 – 984 4 - 1019 » | Colonne « Amplitude attendue par composante » 64–940 : plage légale (tv). Le document n'emploie pas le mot « plage légale ». | |
| `video.y_min_legal`<br>Niveau du noir de la luminance Y en valeur de code 10 bits (ex. 64) | `64` | 5 | « 10 bits 64 – 940 20 – 984 4 - 1019 » | Colonne « Amplitude attendue par composante » ; même valeur que BT.709 et R 103. | |
| `video.y_max_legal`<br>Niveau du blanc nominal de la luminance Y en valeur de code 10 bits (ex. 940) | `940` | 5 | « 10 bits 64 – 940 20 – 984 4 - 1019 » | Colonne « Amplitude attendue par composante » ; même valeur que BT.709 et R 103. | |
| `video.max_out_of_range_area_pct`<br>Surface de l'image hors tolérance, en pourcentage : seuil d'erreur | `1.0` | 5 | « La proportion de pixels dont les valeurs sont hors « Color Gamut » (voir tableau ci-dessus) ne doit pas excéder 1% du nombre total de pixels de l’image active. » | Validé par Vincent le 25/10/2026. | |
| `video.out_of_range_area_error`<br>Erreur si la surface hors tolérance dépasse strictement le seuil (above) ou l'atteint (at_least) | `above` | 5 | « La proportion de pixels dont les valeurs sont hors « Color Gamut » (voir tableau ci-dessus) ne doit pas excéder 1% du nombre total de pixels de l’image active. » | « ne doit pas excéder 1% » : erreur strictement au-delà de 1 % (arbitrage de Damien, 28/10/2026). | |
| `audio.sample_rate`<br>Fréquence d'échantillonnage audio en Hz (ex. 48000) | `48000` | 10 | « Fréquence d’échantillonnage : 48 kHz » | Validé par Vincent le 25/10/2026. | |
| `audio.bit_depth`<br>Quantification audio en bits (ex. 24) | `24` | 10 | « Quantification linéaire : 24 Bits pour le format PCM » | Validé par Vincent le 25/10/2026. « 20 Bits avant encodage Dolby E » ne concerne pas le PCM. | |
| `audio.bit_depth_allowed`<br>Quantifications audio acceptées en bits (ex. [24, 16]) | `[24]` | 16 | « Chaque piste audio du fichier MXF transportera un flux de type AES3, de résolution audio 24 bits, à 48 kHz de fréquence d’échantillonnage. » | Validé par Vincent le 25/10/2026. | |
| `audio.same_bit_depth_all_tracks`<br>Toutes les pistes doivent avoir la même quantification | `true` | 16 | « Chaque piste audio du fichier MXF transportera un flux de type AES3, de résolution audio 24 bits, à 48 kHz de fréquence d’échantillonnage. » | Validé par Vincent le 25/10/2026. | |
| `audio.channel_layout`<br>Organisation des pistes : stereo_pairs (pistes gérées par paires AES) | `stereo_pairs` | 16 | « Les fichiers MXF Prêts à Diffuser comporteront 8 canaux audio, chaque canal distinct étant transporté par une piste AES3 distincte. » | Validé par Vincent le 25/10/2026. Le nombre de canaux (8) n'a pas de champ : voir « sans valeur ». | |
| `audio.dual_mono_must_be_identical`<br>Une version mono doit être livrée en double mono identique et en phase | `true` | 11 | « ces deux pistes contenant le signal monophonique seront strictement identiques et en phase » | §2.2.5.1 Mono, livré sur deux pistes contiguës. | |
| `audio.alignment_tone.hz`<br>Fréquence du signal d'alignement en Hz | `1000.0` | 8 | « Un signal d’alignement 1000 Hz à -18 dBFS doit afficher un niveau de Loudness de -18 LUFS sur un équipement de mesure en EBU Mode, si le signal est présent sur les canaux gauche et droite d’un programme stéréo. » | Validé par Vincent le 25/10/2026. | |
| `audio.alignment_tone.dbfs`<br>Niveau du signal d'alignement en dBFS | `-18.0` | 8 | « Un signal d’alignement 1000 Hz à -18 dBFS doit afficher un niveau de Loudness de -18 LUFS sur un équipement de mesure en EBU Mode, si le signal est présent sur les canaux gauche et droite d’un programme stéréo. » | Validé par Vincent le 25/10/2026. | |
| `audio.true_peak_max_dbtp`<br>Niveau crête vrai (true peak) maximal en dBTP (ex. -1 ou -3) | `-3.0` | 8 | « Le niveau des crêtes du signal audio, mesuré en True Peak, ne doit pas dépasser -3,0 dBTP. » | Validé par Vincent le 25/10/2026. Le tableau p. 9 donne -3,0 dB TP pour les deux colonnes (courts et longs) : un seul champ dans PAD Guard. | |
| `audio.av_sync_ms.audio_early_max`<br>Avance maximale du son sur l'image, en ms | `20.0` | 10 | « Soit une avance maximale du son sur l’image de 20ms » | Validé par Vincent le 25/10/2026. | |
| `audio.av_sync_ms.audio_late_max`<br>Retard maximal du son sur l'image, en ms | `40.0` | 10 | « Soit un retard maximum du son sur l’image de 40ms. » | Validé par Vincent le 25/10/2026. | |
| `audio.loudness.long_program_min_seconds`<br>Durée en secondes au-delà de laquelle un programme est « long » | `120` | 9 | « Programme long : un programme dont la durée est supérieure à 2 minutes. » | RT 040 : court = durée inférieure ou égale à 2 minutes, long = strictement plus de 2 minutes ; PAD Guard applique la même frontière (2:00 exactement = court, arbitrage de Damien du 28/10/2026). | |
| `audio.loudness.long.integrated_lufs`<br>Loudness intégré cible du programme en LUFS (ex. -23) | `-23.0` | 9 | « Mesure du niveau d’intensité \| -23,0 LUFS \| -23,0 LUFS ± 1,0 LU » | Tableau p. 9, colonne « Programmes longs ». Validé par Vincent le 25/10/2026 avec la citation p. 14 (« "Dialog level" - 23,0 LUFS ± 1 (A mesurer) ») : même valeur. | |
| `audio.loudness.long.integrated_tolerance_lu`<br>Tolérance autour du loudness intégré cible, en LU (ex. 1 pour ± 1 LU) | `1.0` | 9 | « Mesure du niveau d’intensité \| -23,0 LUFS \| -23,0 LUFS ± 1,0 LU » | Tableau p. 9, colonne « Programmes longs » (± 1,0 LU) ; la colonne « Programmes courts » n'a pas de tolérance. | |
| `audio.loudness.long.lra_max_lu`<br>Plage de loudness (LRA) maximale en LU | `20.0` | 9 | « Excursion dynamique (Loudness Range ou LRA) ≤ 20,0 LU » | Validé par Vincent le 25/10/2026. Programmes courts : « Non mesurée ». | |
| `audio.loudness.long.lra_recommended_range_lu`<br>Plage de LRA recommandée en LU [min, max] (information) | `[5.0, 20.0]` | 9 | « Excursion dynamique (Loudness Range ou LRA) ≤ 20,0 LU Il est conseillé de dépasser une valeur de 5 LU » | Information seulement (aucune anomalie) : « conseillé de dépasser 5 LU », maximum 20 LU. Le minimum est un conseil, pas une exigence. | |
| `audio.loudness.long.short_term_dialogue_excursion_lu`<br>Excursion admise du loudness short term (3 s) autour de la cible pour le dialogue, en LU | `7.0` | 9 | « la mesure d’intensité sonore court terme, sur les passages du programme comportant des dialogues, devra cibler le niveau moyen de -23,0 LUFS et s’autoriser une excursion maximale de 7 LU autour de ce niveau cible » | Tableau p. 9 : colonne « Programmes longs » « -30,0 ≤ Short term des dialogues ≤ -16,0 en LUFS » (-23 ± 7) ; colonne « Programmes courts » « Non mesurée » : aucune valeur pour les courts. | |
| `audio.loudness.short.integrated_lufs`<br>Loudness intégré cible du programme en LUFS (ex. -23) | `-23.0` | 9 | « Mesure du niveau d’intensité \| -23,0 LUFS \| -23,0 LUFS ± 1,0 LU » | Tableau p. 9, colonne « Programmes courts » : -23,0 LUFS sans tolérance écrite ; la tolérance vient de R 128 s1 par renvoi (± 0,2 LU). Sur demande motivée, un programme court peut être plus bas (p. 9) : cas particulier, non modélisé. | |
| `audio.loudness.short.short_term_max_lufs`<br>Loudness short term (3 s) maximal en LUFS | `-20.0` | 9 | « Niveau maximum de la mesure d’intensité sonore court terme (Max Short Term Loudness) \| ≤ -20,0 LUFS \| Non mesuré » | Tableau p. 9, colonne « Programmes courts » (Max Short Term Loudness) ; programmes longs : « Non mesuré ». RT 040 l'emporte sur R 128 s1 (-18,0 LUFS). | |

## Lu dans la norme, sans valeur dans PAD Guard

| Sujet | Page | Citation | Pourquoi aucune valeur | OK / correction |
|---|---|---|---|---|
| format.containers (MXF OP1a, AS-10) | 15 | « d’un seul fichier MXF Op1a contenant l’essence vidéo et les essences audio associées » | Le conteneur est un paramètre interne de PAD Guard : il se fixe dans le profil du diffuseur (la France TV le précise dans son annexe), pas dans une norme. | |
| format.field_order, format.delivery.scan (1080i) | 4 | « Les formats 1080/25p et 1080/25PsF sont proscrits. » | Entrelacé exigé, mais l'ordre des trames (TFF ou BFF) n'est pas écrit : PAD Guard demande l'un ou l'autre, aucune valeur n'est inventée. | |
| video.y_tolerance_low_pct / high_pct, video.rgb_min_pct / max_pct | 5 | « soit 5-246 en 8 bits (voir le tableau ci-dessous) » | Écrit en valeurs de code (20–984 en 10 bits), pas en pourcentage : la conversion (-5 % / 105 %) n'est pas écrite. Ces valeurs viennent de R 103, auquel RT 040 renvoie (même plage). | |
| format.letterbox (suppression verticale) | 5 | « Une tolérance de +/- 2 lignes est admise » | Lignes données par trame (21 à 560, 540 lignes) ; PAD Guard attend des lignes d'image et les pixels actifs, que le tableau ne donne pas. La tolérance de lignes est un paramètre interne. | |
| structure.timecode.program_start | 15 | « Le début de programme (première image et premier son utile) doit commencer obligatoirement à un Time Code horaire entier » | N'importe quelle heure pleine (00:00:00:00, 01:00:00:00, 10:00:00:00…) : PAD Guard attend un timecode précis. | |
| structure.leaders, structure.black (amorce, noirs) | 15 | « restent à la discrétion de l'éditeur » | Laissé à chaque diffuseur. | |
| audio.max_pairs (8 canaux) | 16 | « Les fichiers MXF Prêts à Diffuser comporteront 8 canaux audio » | Nombre exact de canaux ; PAD Guard n'a qu'un maximum de paires, et 4 paires n'est pas écrit. À fixer dans le profil du diffuseur. | |
| audio.loudness.short.integrated_tolerance_lu | 9 | « les programmes courts pourront présenter une mesure d'intensité sonore en Integrated Loudness inférieure à -23,0 LUFS » | Pas de tolérance écrite pour les programmes courts ; elle vient de R 128 s1 par renvoi. | |
| audio.loudness.short.lra_max_lu | 9 | « Excursion dynamique (Loudness Range ou LRA) Non mesurée » | Programmes courts : non mesurée. | |
| audio.loudness.short.short_term_dialogue_excursion_lu | 9 | « Plage d’excursion de l’intensité Non mesurée » | Programmes courts : non mesurée (la valeur de 7 LU est celle des programmes longs). | |
| audio.loudness.long.short_term_max_lufs | 9 | « Niveau maximum de la mesure ≤ -20,0 LUFS Non mesuré » | Programmes longs : non mesuré (-20,0 LUFS est celui des programmes courts). | |
| audio.phase_min_correlation | 11 | « la phase doit être très majoritairement positive » | Aucun seuil chiffré. | |
| Dolby E | 10 | « Les formats Dolby E doivent être exempts d’erreur CRC » | PAD Guard ne décode pas le Dolby E. | |

## Champs absents

Tous les autres champs du profil (codecs, colorimétrie, structure, PSE, zones de sécurité…) : RT 040 ne les fixe pas, ou renvoie à une norme absente de normes/ (SMPTE 274M, BT.1886, AS-10, BS.775, Tech 3276) ou présente (BT.709, R 103, R 128 et s1, dont les valeurs s'appliquent par renvoi).

## Validation

Pour chaque ligne : la valeur correspond-elle au sens du document ? Corrections dans le relevé (`normes/releves/cst_rt040.yaml`), puis `uv run pad-guard releve-norme normes/releves/cst_rt040.yaml`, qui réécrit ce tableau et efface la signature ; relecture complète, puis `uv run pad-guard signer-norme cst_rt040 --par "Vincent"` écrit la signature dans `normes/cst_rt040.yaml`.

Relu par : ____________________  le : ____________
