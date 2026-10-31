# Recommandation UIT-R BT.1886 — Reference electro-optical transfer function for flat panel displays used in HDTV studio production (BT.1886, 03/2011) : relevé des valeurs

> **Comment relire** (la signature ne porte que sur ce tableau)
>
> 1. Pour chaque ligne, ouvrir le PDF de la norme (dossier `normes\sources\`) à la page indiquée et comparer la valeur à la citation.
> 2. Dans la colonne « OK / correction », écrire `OK`, ou noter la correction (valeur juste, page, citation).
> 3. Un champ absent du tableau n'est pas contrôlé par cette norme.
> 4. Une correction se fait par `releve-norme` (ligne modifiée avec sa citation), puis nouvelle relecture.
> 5. Signer : `uv run pad-guard signer-norme itu_bt1886 --par "Vincent"` (refusé si la norme a changé depuis ce tableau).

Document : `normes/sources/TV/RECOMMENDATION ITU-R BT.1886 - Reference Electro-Optical Transfer Function (EOTF) for flat panel displays used in HDTV studio production.pdf` (SHA-256 `796e4267c81907253a9792b2c7b0aba9d104128f2aa2ad9ba0ca043175a74671`).
Relevé par Claude Code (décision de Damien du 28/10/2026 : relevé sans questionnaire) le 28/10/2026 : `normes/releves/itu_bt1886.yaml`.
Aucune valeur du profil : pas de fichier dans `normes/`.

Chaque citation a été retrouvée par `pad-guard releve-norme` dans la page indiquée ; pour une valeur chiffrée, le nombre est dans la citation, et dans un tableau la colonne correspond au champ. Le code ne juge pas du sens : c'est l'objet de cette relecture.

## Valeurs

| Champ | Valeur | Page | Citation | Remarque | OK / correction |
|---|---|---|---|---|---|
| (aucune) | | | | | |

## Lu dans la norme, sans valeur dans PAD Guard

| Sujet | Page | Citation | Pourquoi aucune valeur | OK / correction |
|---|---|---|---|---|
| EOTF de référence | 3 | « that the reference EOTF for displays used in HDTV production and programme interchange should be the one specified in Annex 1 » | Réglage des écrans de contrôle, pas une propriété du fichier ; aucun champ. | |
| Gamma de l'écran | 4 | « Exponent of power function, γ = 2.404 » | Paramètre d'écran. La balise de transfert du fichier reste celle de BT.709 (bt709). | |
| Codes 10 bits | 4 | « 10-bit digital code values “D” map into values of V per the following equation: V = (D–64)/876 » | Même plage légale 64-940 que BT.709 (où elle est relevée). | |

## Champs absents

BT.1886 ne fixe rien que PAD Guard mesure dans un fichier.

## Validation

Pour chaque ligne : la valeur correspond-elle au sens du document ? Corrections dans le relevé (`normes/releves/itu_bt1886.yaml`), puis `uv run pad-guard releve-norme normes/releves/itu_bt1886.yaml`, qui réécrit ce tableau et efface la signature ; relecture complète, aucune valeur n'est appliquée par PAD Guard : ce tableau se lit, rien n'est à signer.

Relu par : ____________________  le : ____________
