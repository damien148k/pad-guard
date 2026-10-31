# EBU R 128 — Loudness normalisation and permitted maximum level of audio signals (V5, novembre 2023 (EBU R 128-2023)) : relevé des valeurs

> **Comment relire** (la signature ne porte que sur ce tableau)
>
> 1. Pour chaque ligne, ouvrir le PDF de la norme (dossier `normes\sources\`) à la page indiquée et comparer la valeur à la citation.
> 2. Dans la colonne « OK / correction », écrire `OK`, ou noter la correction (valeur juste, page, citation).
> 3. Un champ absent du tableau n'est pas contrôlé par cette norme.
> 4. Une correction se fait par `releve-norme` (ligne modifiée avec sa citation), puis nouvelle relecture.
> 5. Signer : `uv run pad-guard signer-norme ebu_r128 --par "Vincent"` (refusé si la norme a changé depuis ce tableau).

Document : `normes/sources/AUDIO/r128.pdf` (SHA-256 `2bd911fc3cd3e53351fcb47039e33aa5cd2ac9e9175a122c24b0308a69ee161c`).
Autre document cité : `normes/sources/AUDIO/Recommendation ITU-R BS.1770-5 (11_2023) Algorithms to measure audio programme loudness and true-peak audio level.pdf` (ITU-R BS.1770-5).
Relevé par Claude Code (décision de Damien du 28/10/2026 : relevé sans questionnaire) le 28/10/2026 : `normes/releves/ebu_r128.yaml`.
Norme comparée à ce relevé (mêmes champs, mêmes valeurs ; fichier inchangé) : `normes/ebu_r128.yaml`.
Empreinte de `normes/ebu_r128.yaml` à la génération de ce tableau : `9b5f3eac09a354332c6c7dc0227b895c92aeea725033b0fc779f48de563adc5b`.

Chaque citation a été retrouvée par `pad-guard releve-norme` dans la page indiquée ; pour une valeur chiffrée, le nombre est dans la citation, et dans un tableau la colonne correspond au champ. Le code ne juge pas du sens : c'est l'objet de cette relecture.

## Normes auxquelles ce document renvoie

Leurs valeurs s'appliquent aussi quand un diffuseur renvoie à ce document (renvoi transitif) ; elles ne sont pas recopiées ici.

| Norme | Citation du renvoi | Version citée | OK / correction |
|---|---|---|---|
| `ebu_r128_s1` | EBU R 128 (2023) p. 4, recommends q) : « that production and normalisation of short-form content (adverts; promos etc.) should be made in compliance with EBU R 128 s1 [7] » |  | |

## Valeurs

| Champ | Valeur | Page | Citation | Remarque | OK / correction |
|---|---|---|---|---|---|
| `audio.loudness.method`<br>Méthode et norme de mesure du loudness (ex. EBU R 128, ITU-R BS.1770) | `ITU-R BS.1770-5 (intégré avec gating, true peak annexe 2) et EBU Tech 3341 (EBU Mode)` | 4 | « that the measurement shall be made with a loudness meter compliant with ITU-R BS.1770 (including the level-gating method described in equation (7)) and EBU Tech 3341 » | Recommends k). Information (méthode de mesure), sans effet sur le verdict. La version -5 est celle du PDF de normes/sources/ ; R 128 cite BS.1770 sans version. Valeur en texte libre : seule la citation est vérifiée par le code. | |
| `audio.loudness.long.integrated_lufs`<br>Loudness intégré cible du programme en LUFS (ex. -23) | `-23.0` | 3 | « that the Programme Loudness Level shall be normalised to a Target Level of −23.0 LUFS » | Recommends h). R 128 ne distingue pas programmes longs et courts : « long » vaut pour toutes les durées tant que le diffuseur ne précise rien (les courts relèvent de R 128 s1, recommends q). | |
| `audio.loudness.long.integrated_tolerance_lu`<br>Tolérance autour du loudness intégré cible, en LU (ex. 1 pour ± 1 LU) | `0.2` | 3 | « that for the implementation of Loudness workflows (for example, in Quality Control environments) a tolerance of ±0.2 LU is allowed in order to take account of measurement errors » | Recommends i), tolérance de contrôle qualité. La tolérance de ± 1,0 LU de h) est réservée aux programmes où la cible n'est pas atteignable (direct) : voir « sans valeur ». | |
| `audio.true_peak_max_dbtp`<br>Niveau crête vrai (true peak) maximal en dBTP (ex. -1 ou -3) | `-1.0` | 4 | « and that the True Peak Level of a programme shall not exceed −1 dBTP (dB True Peak) during production (linear audio) » | Recommends m). Mesure selon BS.1770 et Tech 3341 ; tolérance de mesure ± 0,3 dB (pas de champ). | |

## Lu dans la norme, sans valeur dans PAD Guard

| Sujet | Page | Citation | Pourquoi aucune valeur | OK / correction |
|---|---|---|---|---|
| Tolérance ± 1,0 LU (direct) | 3 | « Where attaining the Target Level is not achievable practically (for example, live programmes), a tolerance of ±1.0 LU is permitted. » | Programmes en direct seulement ; PAD Guard contrôle des PAD enregistrés. | |
| audio.loudness.long.lra_max_lu | 4 | « that the measure Loudness Range (measured in compliance with EBU Tech 3342 [6]) may be used to evaluate the loudness variation of a programme » | « may be used » : aucune valeur maximale. | |
| audio.loudness.short (renvoi à R 128 s1) | 4 | « that production and normalisation of short-form content (adverts; promos etc.) should be made in compliance with EBU R 128 s1 [7] » | R 128 renvoie à R 128 s1 pour les programmes courts : le renvoi est déclaré dans ebu_r128.yaml (meta.refers_to, arbitrage de Damien du 28/10/2026) ; les valeurs sont dans normes/ebu_r128_s1.yaml. | |
| Tolérance du true peak | 4 | « The measurement tolerance is ±0.3 dB (for signals with a bandwidth limited to 20 kHz). » | Pas de champ dans PAD Guard. | |
| Algorithme de mesure (BS.1770-5) | 1 (ITU-R BS.1770-5) | « Algorithms to measure audio programme loudness and true-peak audio level » | Méthode, pas de seuil : gating, fenêtres et true peak sont appliqués par le code de mesure (measure/), conformément à BS.1770-5 et Tech 3341. | |

## Champs absents

Tous les autres champs : R 128 ne fixe que la cible, sa tolérance de contrôle et le true peak. LRA, short-term et momentary « may be used » sans valeur.

## Validation

Pour chaque ligne : la valeur correspond-elle au sens du document ? Corrections dans le relevé (`normes/releves/ebu_r128.yaml`), puis `uv run pad-guard releve-norme normes/releves/ebu_r128.yaml`, qui réécrit ce tableau et efface la signature ; relecture complète, puis `uv run pad-guard signer-norme ebu_r128 --par "Vincent"` écrit la signature dans `normes/ebu_r128.yaml`.

Relu par Vincent Lagarrigue le 31/10/2026 (pad-guard signer-norme ; empreinte du tableau `e48ea4afd5d32cc4dabd9989399f2cb32a959dbb928507cf554a5f930b8686ad`, écrite dans `normes/ebu_r128.yaml`).
