# EBU Tech 3342 — Loudness Range: a measure to supplement EBU R 128 loudness normalization (novembre 2023) : relevé des valeurs

Document : `normes/sources/AUDIO/tech3342.pdf` (SHA-256 `8b9fcfd268e1eea067cbc990938752ee47377904d7180c327f79b19bf2c806c3`).
Relevé par Claude Code (décision de Damien du 28/10/2026 : relevé sans questionnaire) le 28/10/2026 : `normes/releves/ebu_tech3342.yaml`.
Aucune valeur du profil : pas de fichier dans `normes/`.

Chaque citation a été retrouvée par `pad-guard releve-norme` dans la page indiquée ; pour une valeur chiffrée, le nombre est dans la citation, et dans un tableau la colonne correspond au champ. Le code ne juge pas du sens : c'est l'objet de cette relecture.

## Valeurs

| Champ | Valeur | Page | Citation | Remarque |
|---|---|---|---|---|
| (aucune) | | | | |

## Lu dans la norme, sans valeur dans PAD Guard

| Sujet | Page | Citation | Pourquoi aucune valeur |
|---|---|---|---|
| Calcul de la LRA : percentiles | 5 | « LRA is defined as the difference between the estimates of the 10th and the 95th percentiles of the distribution. » | Méthode appliquée par le code de mesure (measure/audio), pas un seuil. |
| Calcul de la LRA : seuil relatif | 5 | « The relative threshold is set to a level of −20 LU relative to the absolute-gated loudness level. » | Méthode, dans le code de mesure. |
| Calcul de la LRA : seuil absolu | 5 | « The absolute threshold is set to −70 LUFS » | Méthode, dans le code de mesure. |
| Programmes très courts | 5 | « measurement of very short programmes, where leading or trailing silence is included, or of programmes consisting, for example, of isolated utterances, could result in misleadingly high values of LRA » | Information ; R 128 s1 déclare la LRA non applicable aux programmes courts. |

## Champs absents

Tech 3342 ne fixe aucune LRA maximale ou minimale : c'est le diffuseur qui la fixe (Arte, RT 040 : 20 LU).

## Validation

Pour chaque ligne : la valeur correspond-elle au sens du document ? Corrections dans le relevé (`normes/releves/ebu_tech3342.yaml`), puis `uv run pad-guard releve-norme normes/releves/ebu_tech3342.yaml` ; `review-profile` reste possible pour une correction ponctuelle.

Relu et validé par : ____________________  le : ____________  signature : ____________________
