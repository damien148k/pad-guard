# Rapport UIT-R BT.2408-6 — Guidance for operational practices in HDR television production (BT.2408-6, 03/2023) : relevé des valeurs

> **Comment relire** (la signature ne porte que sur ce tableau)
>
> 1. Pour chaque ligne, ouvrir le PDF de la norme (dossier `normes\sources\`) à la page indiquée et comparer la valeur à la citation.
> 2. Dans la colonne « OK / correction », écrire `OK`, ou noter la correction (valeur juste, page, citation).
> 3. Un champ absent du tableau n'est pas contrôlé par cette norme.
> 4. Une correction se fait par `releve-norme` (ligne modifiée avec sa citation), puis nouvelle relecture.
> 5. Signer : `uv run pad-guard signer-norme itu_bt2408 --par "Vincent"` (refusé si la norme a changé depuis ce tableau).

Document : `normes/sources/HDR_COULEUR/REPORT  ITU-R  BT.2408-6 – Guidance for operational practices in HDR television production.pdf` (SHA-256 `5e17d5bad48585f6f5c8a170c0bc929ee1f4d0da9462071982569c0d70eb5f3d`).
Relevé par Claude Code (décision de Damien du 28/10/2026 : relevé sans questionnaire) le 28/10/2026 : `normes/releves/itu_bt2408.yaml`.
Aucune valeur du profil : pas de fichier dans `normes/`.

Chaque citation a été retrouvée par `pad-guard releve-norme` dans la page indiquée ; pour une valeur chiffrée, le nombre est dans la citation, et dans un tableau la colonne correspond au champ. Le code ne juge pas du sens : c'est l'objet de cette relecture.

## Valeurs

| Champ | Valeur | Page | Citation | Remarque | OK / correction |
|---|---|---|---|---|---|
| (aucune) | | | | | |

## Lu dans la norme, sans valeur dans PAD Guard

| Sujet | Page | Citation | Pourquoi aucune valeur | OK / correction |
|---|---|---|---|---|
| Blanc de référence HDR | 7 | « of 203 cd/m2 on a PQ display or on an HLG display that has a nominal peak luminance capability of 1 000 cd/m2 » | Niveau de référence (203 cd/m², 58 % PQ, 75 % HLG, tableau 1 p. 8) : pas de champ HDR dans le profil (phase 7). | |
| Repères de forme d'onde | 8 | « A 75%-HLG or 58%-PQ marker on a waveform monitor, representing the reference level » | Pratique d'exploitation, pas un seuil de conformité. | |
| Plage pleine PQ | 11 | « the full range signal representation of PQ should be used only when all parties agree » | Même règle que BT.2100 (plage légale par défaut) ; la valeur vient de BT.2100. | |

## Champs absents

BT.2408 est un guide : il ne fixe aucune valeur que le profil sait porter aujourd'hui.

## Validation

Pour chaque ligne : la valeur correspond-elle au sens du document ? Corrections dans le relevé (`normes/releves/itu_bt2408.yaml`), puis `uv run pad-guard releve-norme normes/releves/itu_bt2408.yaml`, qui réécrit ce tableau et efface la signature ; relecture complète, aucune valeur n'est appliquée par PAD Guard : ce tableau se lit, rien n'est à signer.

Relu par : ____________________  le : ____________
