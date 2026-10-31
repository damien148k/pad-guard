# Recommandation UIT-R BT.709-6 — Valeurs des paramètres des normes de TVHD pour la production et l'échange international de programmes (BT.709-6, 06/2015) : relevé des valeurs

> **Comment relire** (la signature ne porte que sur ce tableau)
>
> 1. Pour chaque ligne, ouvrir le PDF de la norme (dossier `normes\sources\`) à la page indiquée et comparer la valeur à la citation.
> 2. Dans la colonne « OK / correction », écrire `OK`, ou noter la correction (valeur juste, page, citation).
> 3. Un champ absent du tableau n'est pas contrôlé par cette norme.
> 4. Une correction se fait par `releve-norme` (ligne modifiée avec sa citation), puis nouvelle relecture.
> 5. Signer : `uv run pad-guard signer-norme itu_bt709 --par "Vincent"` (refusé si la norme a changé depuis ce tableau).

Document : `normes/sources/TV/Parameter values for the HDTV standards for production and international programme exchange.pdf` (SHA-256 `460b9e95d473b4344bd468e2e9f9739e03319e74038a5a5e87ba76fa62afdd60`).
Relevé par Claude Code (décision de Damien du 28/10/2026 : relevé sans questionnaire) le 28/10/2026 : `normes/releves/itu_bt709.yaml`.
Norme écrite à partir de ce relevé : `normes/itu_bt709.yaml`.
Empreinte de `normes/itu_bt709.yaml` à la génération de ce tableau : `875de84bf5a79469287009e13d2c6fc48c9a51e701fe08f425a793e6965b9d04`.

Chaque citation a été retrouvée par `pad-guard releve-norme` dans la page indiquée ; pour une valeur chiffrée, le nombre est dans la citation, et dans un tableau la colonne correspond au champ. Le code ne juge pas du sens : c'est l'objet de cette relecture.

## Valeurs

| Champ | Valeur | Page | Citation | Remarque | OK / correction |
|---|---|---|---|---|---|
| `format.width`<br>Largeur de l'image en pixels (ex. 1920) | `1920` | 5 | « 2.2 Samples per active line 1 920 » | Partie 2, §2.2 « Picture characteristics ». | |
| `format.height`<br>Hauteur de l'image en lignes (ex. 1080) | `1080` | 5 | « 2.4 Active lines per picture 1 080 » | Partie 2, §2.4. | |
| `format.bit_depth_allowed`<br>Profondeurs d'image acceptées en bits par composante (ex. 10) | `[8, 10]` | 7 | « 4.5 Coding format Linear 8 or 10 bits/component » | §4.5. Un fichier 12 bits sort de BT.709 (recommandation, plafonnée à mineur sauf renvoi du diffuseur). | |
| `format.color_range`<br>Plage de codage : tv (légale, 64-940 en 10 bits) ou pc (pleine) | `tv` | 7 | « Black level R, G, B, Y 16 64 » | §4.6 : noir à 64 et blanc nominal à 940 (10 bits) : plage légale. BT.709 ne définit pas de plage pleine. | |
| `format.color_primaries`<br>Primaires colorimétriques attendues (ex. bt709 ; coherent : cohérentes avec le fichier) | `bt709` | 5 | « Red (R) 0.640 0.330 » | §1.3 : primaires rouge 0,640/0,330, vert 0,300/0,600, bleu 0,150/0,060 ; blanc D65 0,3127/0,3290 (§1.4). « bt709 » est le nom de la balise ffprobe de ces primaires. Valeur en texte libre : seule la citation est vérifiée par le code. | |
| `format.color_transfer`<br>Fonction de transfert attendue (ex. bt709 ; coherent : cohérente avec le fichier) | `bt709` | 5 | « Overall opto-electronic transfer V 1.099 L0.45 – 0.099 for 1 L 0.018 » | §1.2 (fonction de transfert de BT.709) ; « bt709 » est le nom de la balise ffprobe. Valeur en texte libre : seule la citation est vérifiée par le code. | |
| `format.color_space`<br>Matrice de couleur attendue (ex. bt709 ; coherent : cohérente avec le fichier) | `bt709` | 6 | « 3.2 Derivation of luminance signal E Y E Y 0.2126E R 0.7152E G 0.0722E B » | §3.2 (matrice de luminance) ; « bt709 » est le nom de la balise ffprobe. Valeur en texte libre : seule la citation est vérifiée par le code. | |
| `video.y_min_legal`<br>Niveau du noir de la luminance Y en valeur de code 10 bits (ex. 64) | `64` | 7 | « Black level R, G, B, Y 16 64 » | §4.6, colonne 10 bits (16 en 8 bits). | |
| `video.y_max_legal`<br>Niveau du blanc nominal de la luminance Y en valeur de code 10 bits (ex. 940) | `940` | 7 | « Nominal peak – R, G, B, Y 235 940 » | §4.6, colonne 10 bits (235 en 8 bits). | |

## Lu dans la norme, sans valeur dans PAD Guard

| Sujet | Page | Citation | Pourquoi aucune valeur | OK / correction |
|---|---|---|---|---|
| format.fps_allowed | 8 | « 5.5 Picture rate (Hz) 60, 60/1.001 30, 30/1.001 50 25 24, 24/1.001 » | BT.709 liste les cadences possibles (60, 50, 30, 25, 24 et leurs variantes /1,001) sans en exiger aucune : la cadence se fixe dans le profil du diffuseur. (Écrites « 30/1.001 », elles ne se vérifient pas comme « 30000/1001 ».) | |
| format.field_order (entrelacé : trame 1 en haut) | 8 | « For interlace and segmented frame systems, 1st active line of field 1 at top of picture » | Ordre de présentation des lignes, pas un ordre de trames exigé du fichier. | |
| Codes réservés (synchronisation) | 7 | « Timing reference 0 and 255 0-3 and 1 020-1 023 » | Utilisés par la détection de plage (rules/engine.py), pas un seuil. | |
| Rapport d'image | 5 | « 2.1 Aspect ratio 16:9 » | Pas de champ dans PAD Guard (la zone active se contrôle par format.letterbox, propre au diffuseur). | |

## Champs absents

Tous les autres champs : BT.709 ne fixe ni codec, ni conteneur, ni tolérances de niveaux (R 103), ni audio.

## Validation

Pour chaque ligne : la valeur correspond-elle au sens du document ? Corrections dans le relevé (`normes/releves/itu_bt709.yaml`), puis `uv run pad-guard releve-norme normes/releves/itu_bt709.yaml`, qui réécrit ce tableau et efface la signature ; relecture complète, puis `uv run pad-guard signer-norme itu_bt709 --par "Vincent"` écrit la signature dans `normes/itu_bt709.yaml`.

Relu par : ____________________  le : ____________
