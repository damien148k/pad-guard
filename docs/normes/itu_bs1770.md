# Recommandation UIT-R BS.1770-5 — Algorithms to measure audio programme loudness and true-peak audio level (BS.1770-5, 11/2023) : relevé des valeurs

> **Comment relire** (la signature ne porte que sur ce tableau)
>
> 1. Pour chaque ligne, ouvrir le PDF de la norme (dossier `normes\sources\`) à la page indiquée et comparer la valeur à la citation.
> 2. Dans la colonne « OK / correction », écrire `OK`, ou noter la correction (valeur juste, page, citation).
> 3. Un champ absent du tableau n'est pas contrôlé par cette norme.
> 4. Une correction se fait par `releve-norme` (ligne modifiée avec sa citation), puis nouvelle relecture.
> 5. Signer : `uv run pad-guard signer-norme itu_bs1770 --par "Vincent"` (refusé si la norme a changé depuis ce tableau).

Document : `normes/sources/AUDIO/Recommendation ITU-R BS.1770-5 (11_2023) Algorithms to measure audio programme loudness and true-peak audio level.pdf` (SHA-256 `615c01958eb5b4eda821c55da77c89376acb782b4a1fef89ccd1f3d7aaf1f857`).
Relevé par Claude Code (décision de Damien du 28/10/2026 : relevé sans questionnaire) le 28/10/2026 : `normes/releves/itu_bs1770.yaml`.
Aucune valeur du profil : pas de fichier dans `normes/`.

Chaque citation a été retrouvée par `pad-guard releve-norme` dans la page indiquée ; pour une valeur chiffrée, le nombre est dans la citation, et dans un tableau la colonne correspond au champ. Le code ne juge pas du sens : c'est l'objet de cette relecture.

## Valeurs

| Champ | Valeur | Page | Citation | Remarque | OK / correction |
|---|---|---|---|---|---|
| (aucune) | | | | | |

## Lu dans la norme, sans valeur dans PAD Guard

| Sujet | Page | Citation | Pourquoi aucune valeur | OK / correction |
|---|---|---|---|---|
| Loudness intégré, seuils de gating | 4 | « gating of 400 ms blocks (overlapping by 75%), where two thresholds are used » | Méthode (blocs de 400 ms, recouvrement 75 %, seuil absolu −70 LKFS, seuil relatif −10 dB) appliquée par le code de mesure (measure/audio), pas un seuil de conformité. | |
| Seuil absolu | 4 | « the first at −70 LKFS » | Méthode, dans le code de mesure. | |
| Seuil relatif | 4 | « the second at −10 dB relative to the level measured after application of the first threshold » | Méthode, dans le code de mesure. | |
| True peak (annexe 2) | 20 | « over-sampling filter increases the sampling rate of the signal from 48 kHz to 192 kHz » | Méthode du true peak (suréchantillonnage x4), dans le code de mesure ; le seuil vient du diffuseur ou de R 128. | |

## Champs absents

BS.1770 ne fixe aucune valeur de conformité (cible, tolérance, maximum) : il définit comment mesurer. Les diffuseurs citent des versions antérieures (-1, -2, -4) ; PAD Guard mesure selon la -5.

## Validation

Pour chaque ligne : la valeur correspond-elle au sens du document ? Corrections dans le relevé (`normes/releves/itu_bs1770.yaml`), puis `uv run pad-guard releve-norme normes/releves/itu_bs1770.yaml`, qui réécrit ce tableau et efface la signature ; relecture complète, aucune valeur n'est appliquée par PAD Guard : ce tableau se lit, rien n'est à signer.

Relu par : ____________________  le : ____________
