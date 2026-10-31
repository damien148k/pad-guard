# EBU R 128 s1 — Loudness parameters for short-form content (adverts, promos, etc.), supplement 1 to R 128 (V3, août 2020) : relevé des valeurs

> **Comment relire** (la signature ne porte que sur ce tableau)
>
> 1. Pour chaque ligne, ouvrir le PDF de la norme (dossier `normes\sources\`) à la page indiquée et comparer la valeur à la citation.
> 2. Dans la colonne « OK / correction », écrire `OK`, ou noter la correction (valeur juste, page, citation).
> 3. Un champ absent du tableau n'est pas contrôlé par cette norme.
> 4. Une correction se fait par `releve-norme` (ligne modifiée avec sa citation), puis nouvelle relecture.
> 5. Signer : `uv run pad-guard signer-norme ebu_r128_s1 --par "Vincent"` (refusé si la norme a changé depuis ce tableau).

Document : `normes/sources/AUDIO/r128s1.pdf` (SHA-256 `1f6eefd407b56f07b16e8f1c61cc3d63502fe85f1362a806b57bed0494114445`).
Relevé par Claude Code (décision de Damien du 28/10/2026 : relevé sans questionnaire) le 28/10/2026 : `normes/releves/ebu_r128_s1.yaml`.
Norme écrite à partir de ce relevé : `normes/ebu_r128_s1.yaml`.
Empreinte de `normes/ebu_r128_s1.yaml` à la génération de ce tableau : `29e5bd4eb8b1493c407ff52ef736d27bcf4101306b8f7432f391f50b06ce3955`.

Chaque citation a été retrouvée par `pad-guard releve-norme` dans la page indiquée ; pour une valeur chiffrée, le nombre est dans la citation, et dans un tableau la colonne correspond au champ. Le code ne juge pas du sens : c'est l'objet de cette relecture.

## Valeurs

| Champ | Valeur | Page | Citation | Remarque | OK / correction |
|---|---|---|---|---|---|
| `audio.loudness.long_program_min_seconds`<br>Durée en secondes au-delà de laquelle un programme est « long » | `120` | 4 | « Short-form content: A programme of short duration (up to approximately 2 minutes) » | « environ 2 minutes, généralement moins de 30 secondes » : la limite n'est pas nette. PAD Guard applique « short » jusqu'à 120 s compris. Un diffuseur qui écrit sa limite l'emporte (RT 040 : 2 minutes). | |
| `audio.loudness.short.integrated_lufs`<br>Loudness intégré cible du programme en LUFS (ex. -23) | `-23.0` | 3 | « the Programme Loudness Level shall be normalised to a Target Level of −23.0 LUFS » | Recommends b). Même cible que R 128 ; c) admet une cible plus basse « on purpose », clairement signalée. | |
| `audio.loudness.short.integrated_tolerance_lu`<br>Tolérance autour du loudness intégré cible, en LU (ex. 1 pour ± 1 LU) | `0.2` | 3 | « a tolerance of ±0.2 LU is allowed in order to take account of measurement errors » | Recommends b), tolérance de mesure en contrôle qualité. | |
| `audio.loudness.short.short_term_max_lufs`<br>Loudness short term (3 s) maximal en LUFS | `-18.0` | 3 | « that the Short-term Loudness Level (measured in compliance with EBU Tech 3341 [2]) shall not exceed −18.0 LUFS (+5.0 LU on the relative scale) » | Recommends d) (Maximum Short-term Loudness, mesuré selon EBU Tech 3341). Tolérance de mesure « +0.2 LU » : pas de champ dans PAD Guard. | |

## Lu dans la norme, sans valeur dans PAD Guard

| Sujet | Page | Citation | Pourquoi aucune valeur | OK / correction |
|---|---|---|---|---|
| audio.loudness.short.lra_max_lu | 3 | « a maximum and/or minimum value for Loudness Range shall not be specified for programmes of this length/genre » | LRA non applicable aux programmes courts. | |
| audio.true_peak_max_dbtp | 3 | « the True Peak Level of the programme shall not exceed −1 dBTP (dB True Peak) for linear audio » | Même valeur que R 128 ; dans PAD Guard le true peak est un seul champ pour toutes les durées : il vient de R 128. | |
| Tolérance du Maximum Short-term Loudness | 3 | « a tolerance of +0.2 LU is allowed in order to take account of measurement errors » | Pas de champ dans PAD Guard (le seuil short-term s'applique sans tolérance). | |

## Champs absents

R 128 s1 ne fixe que les paramètres de loudness des programmes courts ; tout le reste vient de R 128 ou du diffuseur.

## Validation

Pour chaque ligne : la valeur correspond-elle au sens du document ? Corrections dans le relevé (`normes/releves/ebu_r128_s1.yaml`), puis `uv run pad-guard releve-norme normes/releves/ebu_r128_s1.yaml`, qui réécrit ce tableau et efface la signature ; relecture complète, puis `uv run pad-guard signer-norme ebu_r128_s1 --par "Vincent"` écrit la signature dans `normes/ebu_r128_s1.yaml`.

Relu par Vincent Lagarrigue le 31/10/2026 (pad-guard signer-norme ; empreinte du tableau `9b07b6ac663764be7df8c222ed924021d6fda99f1cf618061b76d9d837913132`, écrite dans `normes/ebu_r128_s1.yaml`).
