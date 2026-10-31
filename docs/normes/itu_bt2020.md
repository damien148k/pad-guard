# Recommandation UIT-R BT.2020-2 — Parameter values for ultra-high definition television systems for production and international programme exchange (BT.2020-2, 10/2015) : relevé des valeurs

> **Comment relire** (la signature ne porte que sur ce tableau)
>
> 1. Pour chaque ligne, ouvrir le PDF de la norme (dossier `normes\sources\`) à la page indiquée et comparer la valeur à la citation.
> 2. Dans la colonne « OK / correction », écrire `OK`, ou noter la correction (valeur juste, page, citation).
> 3. Un champ absent du tableau n'est pas contrôlé par cette norme.
> 4. Une correction se fait par `releve-norme` (ligne modifiée avec sa citation), puis nouvelle relecture.
> 5. Signer : `uv run pad-guard signer-norme itu_bt2020 --par "Vincent"` (refusé si la norme a changé depuis ce tableau).

Document : `normes/sources/TV/R-REC-BT.2020-2-201510-I!!PDF-E.pdf` (SHA-256 `eed65cf78c95923964c5420ac4f60d1c83f68823c7a71b05a5e31818ebd03374`).
Relevé par Claude Code (décision de Damien du 28/10/2026 : relevé sans questionnaire) le 28/10/2026 : `normes/releves/itu_bt2020.yaml`.
Norme écrite à partir de ce relevé : `normes/itu_bt2020.yaml`.
Empreinte de `normes/itu_bt2020.yaml` à la génération de ce tableau : `590cd317b6d67d6ffa87a4b623635bbe46c47bac37a504ec2bec811f136f117c`.

Chaque citation a été retrouvée par `pad-guard releve-norme` dans la page indiquée ; pour une valeur chiffrée, le nombre est dans la citation, et dans un tableau la colonne correspond au champ. Le code ne juge pas du sens : c'est l'objet de cette relecture.

## Valeurs

| Champ | Valeur | Page | Citation | Remarque | OK / correction |
|---|---|---|---|---|---|
| `format.field_order`<br>Balayage attendu : progressive, psf (progressif en deux trames), tt, bb, tb ou bt (entrelacé) | `progressive` | 5 | « Scan mode Progressive » | Tableau 2 : UHDTV progressif seulement. | |
| `format.bit_depth_allowed`<br>Profondeurs d'image acceptées en bits par composante (ex. 10) | `[10, 12]` | 7 | « Coding format 10 or 12 bits per component » | Tableau 5. | |
| `format.color_primaries`<br>Primaires colorimétriques attendues (ex. bt709 ; coherent : cohérentes avec le fichier) | `bt2020` | 5 | « Red primary (R) 0.708 0.292 » | Tableau 3 : rouge 0,708/0,292, vert 0,170/0,797, bleu 0,131/0,046, blanc D65. « bt2020 » est le nom de la balise ffprobe de ces primaires. Valeur en texte libre : seule la citation est vérifiée par le code. | |
| `format.color_range`<br>Plage de codage : tv (légale, 64-940 en 10 bits) ou pc (pleine) | `tv` | 8 | « Black level DR', DG', DB', DY', DY' C 64 256 » | Tableau 5 (fin) : noir 64, blanc nominal 940 en 10 bits : plage légale. | |
| `video.y_min_legal`<br>Niveau du noir de la luminance Y en valeur de code 10 bits (ex. 64) | `64` | 8 | « Black level DR', DG', DB', DY', DY' C 64 256 » | Tableau 5 (fin), 10 bits (256 en 12 bits). | |
| `video.y_max_legal`<br>Niveau du blanc nominal de la luminance Y en valeur de code 10 bits (ex. 940) | `940` | 8 | « Nominal Peak DR', DG', DB', DY', DY' C 940 3 760 » | Tableau 5 (fin), 10 bits (3 760 en 12 bits). | |

## Lu dans la norme, sans valeur dans PAD Guard

| Sujet | Page | Citation | Pourquoi aucune valeur | OK / correction |
|---|---|---|---|---|
| format.width / format.height | 4 | « Pixel count Horizontal × vertical \| 7 680 × 4 320 \| 3 840 × 2 160 » | Deux définitions possibles : PAD Guard n'a qu'une largeur et une hauteur ; à fixer dans le profil du diffuseur. | |
| format.fps_allowed | 5 | « Frame frequency (Hz) 120, 120/1.001, 100, 60, 60/1.001, 50, 30, 30/1.001, 25, 24, 24/1.001 » | Liste des cadences possibles, aucune exigée : à fixer dans le profil du diffuseur. | |
| format.color_space | 6 | « Constant luminance Non-constant luminance » | Deux matrices possibles (luminance constante ou non) : balise bt2020c ou bt2020nc, à fixer par le diffuseur. | |
| format.color_transfer | 6 | « α = 1.099 and β = 0.018 for 10-bit systems » | Fonction de transfert SDR de BT.2020 (balise bt2020-10 ou bt2020-12 selon la profondeur) ; en HDR, PQ ou HLG de BT.2100. Pas de valeur unique. | |

## Champs absents

BT.2020 ne fixe ni codec, ni conteneur, ni tolérances de niveaux, ni audio.

## Validation

Pour chaque ligne : la valeur correspond-elle au sens du document ? Corrections dans le relevé (`normes/releves/itu_bt2020.yaml`), puis `uv run pad-guard releve-norme normes/releves/itu_bt2020.yaml`, qui réécrit ce tableau et efface la signature ; relecture complète, puis `uv run pad-guard signer-norme itu_bt2020 --par "Vincent"` écrit la signature dans `normes/itu_bt2020.yaml`.

Relu par Vincent Lagarrigue le 31/10/2026 (pad-guard signer-norme ; empreinte du tableau `fcb649bd8ce8e9087685faf888913cf108c97fd11f14d36b646763ab1f45310e`, écrite dans `normes/itu_bt2020.yaml`).
