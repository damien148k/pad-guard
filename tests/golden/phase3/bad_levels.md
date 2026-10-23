# Rapport de contrôle PAD — bad_levels.mov

## 1. En-tête

| | |
|---|---|
| Fichier | bad_levels.mov |
| Durée | 00:00:20:00 (500 images à 25/1 i/s) |
| Timecode | 09:59:50:00 → 10:00:09:24 |
| Vidéo | prores HQ, 1920x1080, yuv422p10le, balayage progressive |
| Profil | test_classic v0.1 (Tests pad-checker), SHA-256 178e44c1515a2efd… |
| Document de référence | tests/fixtures/make_fixtures.sh |
| Version de pad-checker | 0.1.0 |

## 2. Statut

**NON-CONFORME** — score 50/100

| Bloquant | Majeur | Mineur | Info |
|---|---|---|---|
| 1 | 1 | 0 | 0 |

Motifs : 1 anomalie(s) bloquante(s) ; 1 anomalie(s) majeure(s), 0 tolérée(s) (règle : NON-CONFORME dès une anomalie bloquante ou plus de 0 anomalie(s) majeure(s)).

## 3. Synthèse

Le fichier « bad_levels.mov » est NON-CONFORME au profil test_classic v0.1 (Tests pad-checker), avec un score de 50/100. L'analyse relève 2 anomalie(s) : 1 bloquant, 1 majeur. Les anomalies bloquantes concernent : blancs hors tolérance. Les anomalies majeures concernent : noirs hors tolérance. Ce rapport est un pré-contrôle interne : il ne remplace pas le contrôle du diffuseur.

*Synthèse générée par gabarit à partir des compteurs (couche IA désactivée).*

## 4. Contrôles de format et de structure

| Contrôle | Attendu | Mesuré | Statut |
|---|---|---|---|
| Conteneur | mov ou mxf | mov | OK |
| Codec et profil | prores HQ, dnxhd DNXHR HQX | prores HQ | OK |
| Format de pixel | yuv422p10le | yuv422p10le | OK |
| Résolution | 1920x1080 | 1920x1080 | OK |
| Cadence | 25/1 | 25/1 | OK |
| Cadence constante | r_frame_rate = avg_frame_rate | 25/1 / 25/1 | OK |
| Balayage | progressive | progressive | OK |
| Colorimétrie : primaires | bt709 | bt709 | OK |
| Colorimétrie : transfert | bt709 | bt709 | OK |
| Colorimétrie : matrice | bt709 | bt709 | OK |
| Plage | tv | tv | OK |
| Cohérence durée / nombre d'images | 500 images | 500.00 images d'après la durée (20.000 s) | OK |
| Timecode de départ présent | présent | 09:59:50:00 | OK |
| Timecode de départ | 09:59:50:00 | 09:59:50:00 | OK |
| Timecode non drop frame | non drop frame | non drop frame | OK |
| Groupe audio VF stéréo (pistes 1, 2) | présent | présent | OK |
| Groupe audio VI stéréo (pistes 3, 4) | facultatif | absent | OK |
| Flux audio 1 : codec | PCM | pcm_s24le | OK |
| Flux audio 1 : fréquence | 48000 Hz | 48000 Hz | OK |
| Flux audio 1 : quantification | 24 bits | 24 bits | OK |
| Intégrité du décodage | 500 images, aucune erreur | 500 images décodées, 0 erreur(s) distincte(s), 0 discontinuité(s) | OK |
| Mire de barres | ebu_75 à 09:59:50:00, au moins 5,0 s | ebu_75 09:59:50:00 → 09:59:54:24 (5,0 s) | OK |
| Son de la mire, piste 1 | 1000 Hz, -18,0 dBFS ± 0,5 dB | 1000 Hz, -18,0 dBFS | OK |
| Son de la mire, piste 2 | 1000 Hz, -18,0 dBFS ± 0,5 dB | 1000 Hz, -18,0 dBFS | OK |
| Noir et silence de tête | au moins 5,0 s avant le programme | 5,0 s (09:59:55:00 → 09:59:59:24) | OK |
| Noir et silence de queue | au moins 0,0 s | aucun | OK |
| Début du programme (première image non noire après la tête) | 10:00:00:00 ± 0 image(s) | 10:00:00:00 | OK |


## 5. Audio

Mesures globales sur le programme : 10:00:00:00 → 10:00:09:24 (début du programme repéré par le timecode). Groupes (profil) : VF stéréo 1-2, VI stéréo 3-4.

| Groupe | Pistes | Loudness intégré | True peak | LRA | Short term max | Corrélation | Silences | Phase |
|---|---|---|---|---|---|---|---|---|
| VF stéréo | 1-2 | -23,0 LUFS | -12,8 dBTP | 0,1 LU | -23,0 LUFS | 1,00 | 0 | 0 |

Règles appliquées : programme long (0,2 min) : -23,0 LUFS ± 1,0 LU, true peak ≤ -3,0 dBTP, LRA ≤ 20,0 LU.

| Piste | Groupe | Crête | True peak | RMS | Échantillons à pleine échelle |
|---|---|---|---|---|---|
| 1 | VF stéréo | -12,9 dBFS | -12,8 dBTP | -25,5 dBFS | 0 |
| 2 | VF stéréo | -12,9 dBFS | -12,8 dBTP | -25,5 dBFS | 0 |

## 6. Anomalies (ordre chronologique)

### Bloquantes et majeures

Anomalies qui décident du verdict : à corriger avant livraison.

| N° | TC début | TC fin | Durée | Type | Valeur max | Seuil | Surface | Gravité | Qualif. suggérée | Vignette |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 10:00:02:00 | 10:00:02:24 | 1,00 s | Blancs hors tolérance | 975 (104,0 %) | 967 (103 %), surface < 1 % | 100,00 % | bloquant | |  |
| 2 | 10:00:05:00 | 10:00:05:24 | 1,00 s | Noirs hors tolérance | 40 (-2,7 %) | 55 (-1 %), surface < 1 % | 100,00 % | majeur | |  |

Détail :

- **1. Y au-dessus de 103 % sur 100,00 % de l'image** — images 300 à 324 — 25 image(s) hors tolérance sur 25 — gravité bloquant (règle : profil de test (fixtures))
- **2. Y sous -1 % sur 100,00 % de l'image** — images 375 à 399 — 25 image(s) hors tolérance sur 25 — gravité majeur (règle : profil de test (fixtures))

### À vérifier (mineures et informations)

Tolérées par le profil : à contrôler à l'image ou à l'écoute. Beaucoup viennent de règles « DEDUIT » (aucun texte du diffuseur ne les chiffre), plafonnées à mineur.

Aucune.



## 7. Annexe

### Niveaux de luminance dans le temps

![Luminance](annexes/luminance.png)

### Loudness momentané dans le temps

![Loudness](annexes/loudness.png)

### Paramètres du profil appliqués

- Vidéo : Y légal 64–940 ; Y toléré -1,0 % / 103,0 % soit 55–967 ; RVB -5,0 % / 105,0 % soit 20–984 (codes 10 bits, bornes incluses) ; anomalie si la surface hors tolérance atteint 1,0 % de l'image.
- Préfiltre avant mesure des niveaux : horizontal 3 points, noyau [1 2 1]/4 (A VERIFIER : EBU R103 ne chiffre pas le noyau).
- Conversion RVB : matrice bt709, chroma 4:2:2 interpolée linéairement, sans écrêtage.
- Structure : amorces « classic », TC de départ 09:59:50:00, programme à 10:00:00:00 (± 0 image(s)) ; noir si y_p99 < 68 et son < -60,0 dBFS.
- Images figées : différence moyenne < 0,50 pendant au moins 2,0 s ; PSE : activé, plus de 3 flashs/s (variation > 10 % de luminance sur plus de 25 % de l'image).
- Audio : true peak ≤ -3,0 dBTP ; silence < -60,0 dBFS pendant plus de 3,0 s ; phase : corrélation < -0,30 pendant plus de 2,0 s.
- Événements : images fusionnées si moins de 12 image(s) les séparent ; durées minimales black_crush 1, freeze 50, gamut 3, white_clip 1 ; 0 anomalie(s) majeure(s) tolérée(s) ; score = 100 - 40*blocking - 10*major - 2*minor.

### Méthodes et limites

- PSE : approximation inspirée d'ITU-R BT.1702 (variations de luminance relative sur l'image entière) ; ce n'est pas un test Harding certifié.
- Qualification suggérée : vide, la couche IA est désactivée.
- Les seuils sont ceux du profil ; une valeur marquée « A VERIFIER » ou « DEDUIT » dans le profil est une interprétation à confirmer.
