# Recommandation UIT-R BT.2100-3 — Image parameter values for high dynamic range television for use in production and international programme exchange (BT.2100-3, 02/2025) : relevé des valeurs

Document : `normes/sources/TV/R-REC-BT.2100-3-202502-I!!PDF-E.pdf` (SHA-256 `f0668803dce2cd67e3780efbe97494c776b7d6b680733c8237fee364f2d412c3`).
Relevé par Claude Code (décision de Damien du 28/10/2026 : relevé sans questionnaire) le 28/10/2026 : `normes/releves/itu_bt2100.yaml`.
Norme écrite à partir de ce relevé : `normes/itu_bt2100.yaml`.

Chaque citation a été retrouvée par `pad-guard releve-norme` dans la page indiquée ; pour une valeur chiffrée, le nombre est dans la citation, et dans un tableau la colonne correspond au champ. Le code ne juge pas du sens : c'est l'objet de cette relecture.

## Valeurs

| Champ | Valeur | Page | Citation | Remarque |
|---|---|---|---|---|
| `format.field_order`<br>Balayage attendu : progressive, psf (progressif en deux trames), tt, bb, tb ou bt (entrelacé) | `progressive` | 4 | « Image Format Progressive » | Tableau 1. |
| `format.bit_depth_allowed`<br>Profondeurs d'image acceptées en bits par composante (ex. 10) | `[10, 12]` | 11 | « Coding format n = 10, 12 bits per component » | Tableau 9 (entiers). Le tableau 10 ajoute une représentation flottante 16 bits, hors des fichiers PAD. |
| `format.color_primaries`<br>Primaires colorimétriques attendues (ex. bt709 ; coherent : cohérentes avec le fichier) | `bt2020` | 5 | « Red primary (R) monochromatic 630 nm 0.708 0.292 » | Tableau 2 : mêmes primaires que BT.2020 (balise ffprobe « bt2020 »). Valeur en texte libre : seule la citation est vérifiée par le code. |
| `format.color_range`<br>Plage de codage : tv (légale, 64-940 en 10 bits) ou pc (pleine) | `tv` | 10 | « The narrow range representation is in widespread use and is considered the default. » | La plage pleine « should not be used for programme exchange unless all parties agree » (même page) : plage légale par défaut. |
| `video.y_min_legal`<br>Niveau du noir de la luminance Y en valeur de code 10 bits (ex. 64) | `64` | 11 | « Black (R' = G' = B' = Y' = I = 0) 64 256 0 0 » | Tableau 9, plage légale 10 bits (0 en plage pleine). |
| `video.y_max_legal`<br>Niveau du blanc nominal de la luminance Y en valeur de code 10 bits (ex. 940) | `940` | 11 | « Nominal Peak (R' = G' = B' = Y' = I = 1) 940 3 760 1 023 4 095 » | Tableau 9, plage légale 10 bits (1 023 en plage pleine). |

## Lu dans la norme, sans valeur dans PAD Guard

| Sujet | Page | Citation | Pourquoi aucune valeur |
|---|---|---|---|
| format.color_transfer | 4 | « the Perceptual Quantization (PQ) or Hybrid Log-Gamma (HLG) specifications described in this Recommendation should be used » | Deux fonctions de transfert (smpte2084 ou arib-std-b67) : à fixer dans le profil du diffuseur. |
| format.width / format.height | 4 | « Container Pixel count 1b Horizontal × Vertical \| 7 680 × 4 320 3 840 × 2 160 1 920 × 1 080 » | Trois définitions possibles : à fixer dans le profil du diffuseur. |
| format.fps_allowed | 4 | « Frame frequency (Hz) 120, 120/1.001,100, 60, 60/1.001, 50, 30, 30/1.001, 25, 24, 24/1.001 » | Liste des cadences possibles, aucune exigée. |
| format.color_space | 10 | « Coded signal \| R', G', B' or Y', C' , C' , or I, C C B R, T, P » | Y'CbCr (bt2020nc) ou ICtCp : à fixer par le diffuseur. |
| Plage pleine | 10 | « The full range representation is newly introduced in this Recommendation and should not be used for programme exchange unless all parties agree. » | Une plage pleine n'est admise que si le diffuseur l'écrit. |

## Champs absents

BT.2100 ne fixe ni codec, ni conteneur, ni tolérances de niveaux, ni métadonnées HDR (ST 2086, absente de normes/).

## Validation

Pour chaque ligne : la valeur correspond-elle au sens du document ? Corrections dans le relevé (`normes/releves/itu_bt2100.yaml`), puis `uv run pad-guard releve-norme normes/releves/itu_bt2100.yaml` ; `review-profile` reste possible pour une correction ponctuelle.

Relu et validé par : ____________________  le : ____________  signature : ____________________
