# Recommandation UIT-R BT.2100-3 — Image parameter values for high dynamic range television for use in production and international programme exchange (BT.2100-3, 02/2025) : relevé des valeurs

> **Comment relire** (la signature ne porte que sur ce tableau)
>
> 1. Pour chaque ligne, ouvrir le PDF de la norme (dossier `normes\sources\`) à la page indiquée et comparer la valeur à la citation.
> 2. Dans la colonne « OK / correction », écrire `OK`, ou noter la correction (valeur juste, page, citation).
> 3. Un champ absent du tableau n'est pas contrôlé par cette norme.
> 4. Une correction se fait par `releve-norme` (ligne modifiée avec sa citation), puis nouvelle relecture.
> 5. Signer : `uv run pad-guard signer-norme itu_bt2100 --par "Vincent"` (refusé si la norme a changé depuis ce tableau).

Document : `normes/sources/TV/R-REC-BT.2100-3-202502-I!!PDF-E.pdf` (SHA-256 `f0668803dce2cd67e3780efbe97494c776b7d6b680733c8237fee364f2d412c3`).
Relevé par Claude Code (décision de Damien du 28/10/2026 : relevé sans questionnaire) le 28/10/2026 : `normes/releves/itu_bt2100.yaml`.
Norme écrite à partir de ce relevé : `normes/itu_bt2100.yaml`.
Empreinte de `normes/itu_bt2100.yaml` à la génération de ce tableau : `d97ab54af7b8736a5e6a71d48f3a8b2fa2ba2c35cbbe8c68507c2ef19dc6d135`.

Chaque citation a été retrouvée par `pad-guard releve-norme` dans la page indiquée ; pour une valeur chiffrée, le nombre est dans la citation, et dans un tableau la colonne correspond au champ. Le code ne juge pas du sens : c'est l'objet de cette relecture.

## Valeurs

| Champ | Valeur | Page | Citation | Remarque | OK / correction |
|---|---|---|---|---|---|
| `format.field_order`<br>Balayage attendu : progressive, psf (progressif en deux trames), tt, bb, tb ou bt (entrelacé) | `progressive` | 4 | « Image Format Progressive » | Tableau 1. | |
| `format.bit_depth_allowed`<br>Profondeurs d'image acceptées en bits par composante (ex. 10) | `[10, 12]` | 11 | « Coding format n = 10, 12 bits per component » | Tableau 9 (entiers). Le tableau 10 ajoute une représentation flottante 16 bits, hors des fichiers PAD. | |
| `format.color_primaries`<br>Primaires colorimétriques attendues (ex. bt709 ; coherent : cohérentes avec le fichier) | `bt2020` | 5 | « Red primary (R) monochromatic 630 nm 0.708 0.292 » | Tableau 2 : mêmes primaires que BT.2020 (balise ffprobe « bt2020 »). Valeur en texte libre : seule la citation est vérifiée par le code. | |
| `format.color_range`<br>Plage de codage : tv (légale, 64-940 en 10 bits) ou pc (pleine) | `tv` | 10 | « The narrow range representation is in widespread use and is considered the default. » | La plage pleine « should not be used for programme exchange unless all parties agree » (même page) : plage légale par défaut. | |
| `video.y_min_legal`<br>Niveau du noir de la luminance Y en valeur de code 10 bits (ex. 64) | `64` | 11 | « Black (R' = G' = B' = Y' = I = 0) 64 256 0 0 » | Tableau 9, plage légale 10 bits (0 en plage pleine). | |
| `video.y_max_legal`<br>Niveau du blanc nominal de la luminance Y en valeur de code 10 bits (ex. 940) | `940` | 11 | « Nominal Peak (R' = G' = B' = Y' = I = 1) 940 3 760 1 023 4 095 » | Tableau 9, plage légale 10 bits (1 023 en plage pleine). | |

## Lu dans la norme, sans valeur dans PAD Guard

| Sujet | Page | Citation | Pourquoi aucune valeur | OK / correction |
|---|---|---|---|---|
| format.color_transfer | 4 | « the Perceptual Quantization (PQ) or Hybrid Log-Gamma (HLG) specifications described in this Recommendation should be used » | Deux fonctions de transfert (smpte2084 ou arib-std-b67) : à fixer dans le profil du diffuseur. | |
| format.width / format.height | 4 | « Container Pixel count 1b Horizontal × Vertical \| 7 680 × 4 320 3 840 × 2 160 1 920 × 1 080 » | Trois définitions possibles : à fixer dans le profil du diffuseur. | |
| format.fps_allowed | 4 | « Frame frequency (Hz) 120, 120/1.001,100, 60, 60/1.001, 50, 30, 30/1.001, 25, 24, 24/1.001 » | Liste des cadences possibles, aucune exigée. | |
| format.color_space | 10 | « Coded signal \| R', G', B' or Y', C' , C' , or I, C C B R, T, P » | Y'CbCr (bt2020nc) ou ICtCp : à fixer par le diffuseur. | |
| Plage pleine | 10 | « The full range representation is newly introduced in this Recommendation and should not be used for programme exchange unless all parties agree. » | Une plage pleine n'est admise que si le diffuseur l'écrit. | |

## Champs absents

BT.2100 ne fixe ni codec, ni conteneur, ni tolérances de niveaux, ni métadonnées HDR (ST 2086, absente de normes/).

## Validation

Pour chaque ligne : la valeur correspond-elle au sens du document ? Corrections dans le relevé (`normes/releves/itu_bt2100.yaml`), puis `uv run pad-guard releve-norme normes/releves/itu_bt2100.yaml`, qui réécrit ce tableau et efface la signature ; relecture complète, puis `uv run pad-guard signer-norme itu_bt2100 --par "Vincent"` écrit la signature dans `normes/itu_bt2100.yaml`.

Relu par Vincent Lagarrigue le 31/10/2026 (pad-guard signer-norme ; empreinte du tableau `627bb5641e389eaa309b8122af8fa967e240460295c91e97a3cae064bb299b3f`, écrite dans `normes/itu_bt2100.yaml`).
