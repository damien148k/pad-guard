# Ce que les consignes Arte V2 changent pour PAD Guard

Source : « Consignes Techniques Globales ARTE G.E.I.E. » V2-01-00, applicable au 1er janvier 2026 (V1-07-3 encore acceptée jusqu'au 31 décembre 2026). Le profil `profiles/arte_hd_sdr.yaml` reprend toutes les valeurs ci-dessous avec le paragraphe source.

## 1. Le PAD Arte n'est pas un ProRes

Le PAD final est un **MXF OP1a, Sony XAVC HD Intra Class 100 CBG**, 1080p50 ou 1080p25, 4:2:2 10 bits, Rec. 709 (§3.2.2.1). Le ProRes HQ et le DNxHD 185 ne sont acceptés que pour les **éléments de production** (rushes, éléments non finalisés, §3.2.2.2), pas pour le PAD.

Conséquence pour l'outil : il contrôle le master ProRes 422 HQ / DNxHR HQX **avant** l'encodage XAVC, avec exactement les règles du PAD (niveaux, audio, timecode, structure). L'encodage XAVC est fait par le prestataire.

## 2. Pas d'amorce, du tout

« Le programme ne doit pas contenir d'amorces de début et de fin » (§3.2.2.1). Le TC In du fichier est `10:00:00:00` et c'est la première image du programme (§3.4.1). Donc : pas de mire, pas de noir de tête, pas de décompte, pas de noir de queue.

Conséquence : la spec v2 a été modifiée pour un mode `structure.leaders: none`. Dans ce mode, une mire ou un noir prolongé en tête est une anomalie bloquante. La tête « classique » (mire + noir) reste disponible pour les autres chaînes.

## 3. Vidéo : exactement EBU R103

- Y entre -1 % et +103 % (-7 mV à 721 mV), RVB entre -5 % et +105 % (-35 mV à 735 mV), mesuré **dans les deux espaces** (§3.2.3).
- Erreur seulement si le dépassement couvre **au moins 1 % de la surface** de l'image, après filtrage des dépassements fugitifs (§3.2.3.3).
- Le document le dit explicitement : 64–940 en 10 bits, 16–235 en 8 bits (§3.2.3.2).
- Tableau des lignes actives par format d'image (§3.2.4) : 1.85 → 1036 lignes, 2.35 → 816 lignes, positions imposées. C'est un contrôle que l'outil peut faire (ajouté en §6.5 de la spec).
- Qualité subjective (§3.2.4.1) : « les noirs ne devront pas être collés ou écrasés ». Non mesurable strictement, mais `black_crush` y répond en partie.

## 4. Audio : plusieurs points qui diffèrent de ce que nous avions

| Point | Arte V2 | Ce que nous avions |
|---|---|---|
| True peak | **-1 dBTP** (§3.3.2.1, §3.3.2.3) | -3 dBTP (CST RT-017) |
| Loudness intégré | -23 LUFS, ±1 LU (programmes > 2 min) ; ±0,5 LU et short term ≤ -20 LUFS pour les programmes ≤ 2 min (§3.3.2.4) | -23 ±1 |
| Short term | ±7 LU autour de la cible sur le dialogue, fenêtre 3 s (§3.3.2.5) | absent |
| LRA | ≤ 20 LU, recommandé 5–15 (§3.3.2.5) | ≤ 20 |
| Pistes | par paires AES, jusqu'à 8 paires ; **aucune piste silencieuse** (§3.2.2.1, §3.3) | mapping libre |
| Mono | double mono, les deux pistes **strictement identiques et en phase** (§3.3.4.1) | absent |
| Quantification | 24 bits (16 bits seulement pour du SD up-converti), identique sur toutes les pistes (§3.3.4) | 24 |
| Synchro A/V | son en avance ≤ 40 ms, en retard ≤ 60 ms (§3.3.3) | absent, non mesurable sans référence |

Les quatre lignes « absent » ont été ajoutées à la spec (§5.3).

## 5. Timecode

TC de début `10:00:00:00`, continu, sans saut ni recouvrement, inscrit dans le Material Package du MXF (§3.4.1). Déjà couvert ; sur le master ProRes (MOV), le TC de départ est lu dans la piste `tmcd`.

## 6. Ce que le document exige mais que l'outil ne peut pas vérifier en v2

- Génériques de fin : 30 s documentaire, 60 s fiction, 2 min cinéma ; génériques silencieux sur fond noir interdits (§6.11). Nécessiterait de reconnaître le générique. Le profil garde les valeurs en « information ».
- Pas de logo de chaîne dans l'image (§6.1).
- Sécu-titres EBU R95 et coins réservés au logo (§3.2.6, §3.2.7, annexe 13.1).
- Tout ce qui concerne les fichiers STL de sous-titres (§3.5, §4), les WAV séparés, les métadonnées de livraison Partner.

## 7. Hors périmètre v2 mais à garder en tête

- **UHD 2160p** et **HDR PQ BT.2020** (§3.2.2.1, profil HDR) : plage 64–940, blanc de référence 203 cd/m² (Y = 572), métadonnées ST 2086 / MaxCLL / MaxFALL dans un XML séparé. L'architecture (seuils dans le profil, primaires paramétrables) doit permettre un profil `arte_uhd_hdr` en v3.
- **1080p50** : accepté par Arte au même titre que 25p. Le profil autorise les deux ; les fixtures de test sont en 25p.

## 8. Réponses de Lumiris (7 octobre 2026)

1. Lumiris livre un **master ProRes 422 HQ au prestataire**, qui fabrique le MXF XAVC. L'outil ne contrôle donc que le master ; la variante `pad_final` a été retirée du profil.
2. Les livraisons suivent la **version actuelle (V2)** des consignes Arte. Pas de profil V1.
3. Audio : **VO, VF, VI**, en trois paires stéréo (pistes 1-2, 3-4, 5-6). La VI n'ayant pas de dialogue, la règle d'excursion short term « dialogue » ne lui est pas appliquée (interprétation à confirmer).
