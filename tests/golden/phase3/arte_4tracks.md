# Rapport de contrôle PAD — arte_4tracks.mov

## 1. En-tête

| | |
|---|---|
| Fichier | arte_4tracks.mov |
| Durée | 00:00:20:00 (500 images à 25/1 i/s) |
| Timecode | 10:00:00:00 → 10:00:19:24 |
| Vidéo | prores HQ, 1920x1080, yuv422p10le, balayage progressive |
| Profil | arte_hd_sdr v1.0 (ARTE G.E.I.E.), SHA-256 17333c0d7973cbfa… |
| Document de référence | Consignes Techniques Globales ARTE G.E.I.E. V2-01-00 (application 01/01/2026) |
| Version de pad-checker | 0.1.0 |

## 2. Statut

**CONFORME** — score 100/100

| Bloquant | Majeur | Mineur | Info |
|---|---|---|---|
| 0 | 0 | 0 | 0 |

Aucune anomalie bloquante, et pas plus de 0 anomalie(s) majeure(s).

## 3. Synthèse

Le fichier « arte_4tracks.mov » est CONFORME au profil arte_hd_sdr v1.0 (ARTE G.E.I.E.), avec un score de 100/100. Aucune anomalie n'a été relevée. Ce rapport est un pré-contrôle interne : il ne remplace pas le contrôle du diffuseur.

*Synthèse générée par gabarit à partir des compteurs (couche IA désactivée).*

## 4. Contrôles de format et de structure

| Contrôle | Attendu | Mesuré | Statut |
|---|---|---|---|
| Conteneur | mov ou mxf | mov | OK |
| Codec et profil | prores HQ, dnxhd DNXHR HQX | prores HQ | OK |
| Format de pixel | yuv422p10le | yuv422p10le | OK |
| Résolution | 1920x1080 | 1920x1080 | OK |
| Cadence | 25/1 ou 50/1 | 25/1 | OK |
| Cadence constante | r_frame_rate = avg_frame_rate | 25/1 / 25/1 | OK |
| Balayage | progressive | progressive | OK |
| Colorimétrie : primaires | bt709 | bt709 | OK |
| Colorimétrie : transfert | bt709 | bt709 | OK |
| Colorimétrie : matrice | bt709 | bt709 | OK |
| Plage | tv | tv | OK |
| Cohérence durée / nombre d'images | 500 images | 500.00 images d'après la durée (20.000 s) | OK |
| Timecode de départ présent | présent | 10:00:00:00 | OK |
| Timecode de départ | 10:00:00:00 | 10:00:00:00 | OK |
| Timecode non drop frame | non drop frame | non drop frame | OK |
| Groupe audio VO (pistes 1, 2) | présent | présent | OK |
| Groupe audio VF (pistes 3, 4) | présent | présent | OK |
| Groupe audio VI (pistes 5, 6) | facultatif | absent | OK |
| Nombre de paires audio | ≤ 8 paires (16 pistes) | 4 piste(s) | OK |
| Flux audio 1 : codec | PCM | pcm_s24le | OK |
| Flux audio 1 : fréquence | 48000 Hz | 48000 Hz | OK |
| Flux audio 1 : quantification | 24 bits ou 16 bits | 24 bits | OK |
| Flux audio 2 : codec | PCM | pcm_s24le | OK |
| Flux audio 2 : fréquence | 48000 Hz | 48000 Hz | OK |
| Flux audio 2 : quantification | 24 bits ou 16 bits | 24 bits | OK |
| Flux audio 3 : codec | PCM | pcm_s24le | OK |
| Flux audio 3 : fréquence | 48000 Hz | 48000 Hz | OK |
| Flux audio 3 : quantification | 24 bits ou 16 bits | 24 bits | OK |
| Flux audio 4 : codec | PCM | pcm_s24le | OK |
| Flux audio 4 : fréquence | 48000 Hz | 48000 Hz | OK |
| Flux audio 4 : quantification | 24 bits ou 16 bits | 24 bits | OK |
| Quantification identique sur toutes les pistes | identique | 24 bits | OK |
| Intégrité du décodage | 500 images, aucune erreur | 500 images décodées, 0 erreur(s) distincte(s), 0 discontinuité(s) | OK |
| Pas de mire dans le fichier | aucune mire | aucune mire | OK |
| Noir et silence de tête | au plus 2,0 s | aucun | OK |
| Noir et silence de queue | au plus 5,0 s | aucun | OK |
| Format d'image (lignes et pixels actifs) | 1.33 (1080 lignes × 1440 px), 1.66 (1080 lignes × 1800 px), 1.77 (1080 lignes × 1920 px), 1.85 (1036 lignes × 1920 px), 2.35 (816 lignes × 1920 px), ± 2 | 1080 lignes (lignes 0 à 1079) × 1920 px (colonnes 0 à 1919), 100 % des échantillons dans cette zone : format 1.77 | OK |


## 5. Audio

Mesures globales sur le programme : 10:00:00:00 → 10:00:19:24 (fichier entier). Groupes (profil) : VO 1-2, VF 3-4, VI 5-6.

| Groupe | Pistes | Loudness intégré | True peak | LRA | Short term max | Corrélation | Silences | Phase |
|---|---|---|---|---|---|---|---|---|
| VO | 1-2 | -23,0 LUFS | -13,1 dBTP | 0,1 LU | -22,9 LUFS | 1,00 | 0 | 0 |
| VF | 3-4 | -23,0 LUFS | -12,1 dBTP | 0,1 LU | -22,9 LUFS | 1,00 | 0 | 0 |

Règles appliquées : programme court (0,3 min) : -23,0 LUFS ± 0,5 LU, true peak ≤ -1,0 dBTP.

| Piste | Groupe | Crête | True peak | RMS | Échantillons à pleine échelle |
|---|---|---|---|---|---|
| 1 | VO | -13,2 dBFS | -13,1 dBTP | -25,8 dBFS | 0 |
| 2 | VO | -13,2 dBFS | -13,1 dBTP | -25,8 dBFS | 0 |
| 3 | VF | -12,4 dBFS | -12,1 dBTP | -25,6 dBFS | 0 |
| 4 | VF | -12,4 dBFS | -12,1 dBTP | -25,6 dBFS | 0 |

## 6. Anomalies (ordre chronologique)

### Bloquantes et majeures

Anomalies qui décident du verdict : à corriger avant livraison.

Aucune.

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
- Structure : amorces « none », TC de départ 10:00:00:00, programme à 10:00:00:00 (± 0 image(s)) ; noir si y_p99 < 68 et son < -60,0 dBFS.
- Images figées : différence moyenne < 0,50 pendant au moins 2,0 s ; PSE : activé, plus de 3 flashs/s (variation > 10 % de luminance sur plus de 25 % de l'image).
- Audio : true peak ≤ -1,0 dBTP ; silence < -60,0 dBFS pendant plus de 3,0 s ; phase : corrélation < -0,30 pendant plus de 2,0 s.
- Événements : images fusionnées si moins de 12 image(s) les séparent ; durées minimales black_crush 1, freeze 50, gamut 1, white_clip 1 ; 0 anomalie(s) majeure(s) tolérée(s) ; score = 100 - 40*blocking - 10*major - 2*minor.

### Méthodes et limites

- PSE : approximation inspirée d'ITU-R BT.1702 (variations de luminance relative sur l'image entière) ; ce n'est pas un test Harding certifié.
- Format d'image : une image toutes les 10 s ; seuls les nombres de lignes et de pixels actifs sont comparés au profil, pas la position des lignes (correspondance avec la numérotation SMPTE à vérifier).
- Short term : seule l'excursion au-dessus de la cible est contrôlée, sur tout le programme ; le dialogue n'est pas détecté automatiquement.
- Qualification suggérée : vide, la couche IA est désactivée.
- Les seuils sont ceux du profil ; une valeur marquée « A VERIFIER » ou « DEDUIT » dans le profil est une interprétation à confirmer.
