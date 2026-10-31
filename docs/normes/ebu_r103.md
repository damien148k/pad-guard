# EBU R 103 — Video signal tolerance in digital television systems (version 3.0, mai 2020) : relevé des valeurs

> **Comment relire** (la signature ne porte que sur ce tableau)
>
> 1. Pour chaque ligne, ouvrir le PDF de la norme (dossier `normes\sources\`) à la page indiquée et comparer la valeur à la citation.
> 2. Dans la colonne « OK / correction », écrire `OK`, ou noter la correction (valeur juste, page, citation).
> 3. Un champ absent du tableau n'est pas contrôlé par cette norme.
> 4. Une correction se fait par `releve-norme` (ligne modifiée avec sa citation), puis nouvelle relecture.
> 5. Signer : `uv run pad-guard signer-norme ebu_r103 --par "Vincent"` (refusé si la norme a changé depuis ce tableau).

Document : `normes/sources/TV/r103.pdf` (SHA-256 `6859c50c2a854d7794540ca534905c4ecda829de3040fbf7985af0aa0c1ec2e5`).
Relevé par Claude Code (décision de Damien du 28/10/2026 : relevé sans questionnaire) le 28/10/2026 : `normes/releves/ebu_r103.yaml`.
Norme comparée à ce relevé (mêmes champs, mêmes valeurs ; fichier inchangé) : `normes/ebu_r103.yaml`.
Empreinte de `normes/ebu_r103.yaml` à la génération de ce tableau : `4e9fe8ecea4bf7600e292cec749be9fc6762d781a2107b3be370ab4b842b6962`.

Chaque citation a été retrouvée par `pad-guard releve-norme` dans la page indiquée ; pour une valeur chiffrée, le nombre est dans la citation, et dans un tableau la colonne correspond au champ. Le code ne juge pas du sens : c'est l'objet de cette relecture.

## Valeurs

| Champ | Valeur | Page | Citation | Remarque | OK / correction |
|---|---|---|---|---|---|
| `video.y_min_legal`<br>Niveau du noir de la luminance Y en valeur de code 10 bits (ex. 64) | `64` | 5 | « 10-bit 64 - 940 20 - 984 4 - 1019 » | Tableau 1, ligne 10 bits, colonne « Nominal Video Range ». | |
| `video.y_max_legal`<br>Niveau du blanc nominal de la luminance Y en valeur de code 10 bits (ex. 940) | `940` | 5 | « 10-bit 64 - 940 20 - 984 4 - 1019 » | Tableau 1, ligne 10 bits, colonne « Nominal Video Range ». | |
| `video.y_tolerance_low_pct`<br>Tolérance basse de la luminance Y en pourcentage de la plage nominale (ex. -1) | `-5.0` | 5 | « 10-bit 64 - 940 20 - 984 4 - 1019 » | Colonne « Preferred Min. / Max. » : 20. P. 4 : « the RGB components and the corresponding Luminance (Y) signal should not normally exceed the “Preferred Minimum/Maximum” range » : même plage pour Y et RVB. Arte (§3.2.3.3) attribue à R 103 une plage Y de -1 % / 103 %, qui n'y figure pas ; le profil Arte garde ses valeurs. Pourcentage écrit en code 10 bits par la norme : le code vérifie le code équivalent (arrondi vers l'extérieur) dans la citation. | |
| `video.y_tolerance_high_pct`<br>Tolérance haute de la luminance Y en pourcentage de la plage nominale (ex. 103) | `105.0` | 5 | « 10-bit 64 - 940 20 - 984 4 - 1019 » | Colonne « Preferred Min. / Max. » : 984 (même plage pour Y et RVB, p. 4). Pourcentage écrit en code 10 bits par la norme : le code vérifie le code équivalent (arrondi vers l'extérieur) dans la citation. | |
| `video.rgb_min_pct`<br>Tolérance basse des composantes R, V, B en pourcentage (ex. -5) | `-5.0` | 5 | « 10-bit 64 - 940 20 - 984 4 - 1019 » | Colonne « Preferred Min. / Max. » : 20. Pourcentage écrit en code 10 bits par la norme : le code vérifie le code équivalent (arrondi vers l'extérieur) dans la citation. | |
| `video.rgb_max_pct`<br>Tolérance haute des composantes R, V, B en pourcentage (ex. 105) | `105.0` | 5 | « 10-bit 64 - 940 20 - 984 4 - 1019 » | Colonne « Preferred Min. / Max. » : 984. Pourcentage écrit en code 10 bits par la norme : le code vérifie le code équivalent (arrondi vers l'extérieur) dans la citation. | |
| `video.max_out_of_range_area_pct`<br>Surface de l'image hors tolérance, en pourcentage : seuil d'erreur | `1.0` | 5 | « measuring equipment should indicate an “Out-of-Gamut” occurrence only after the error exceeds 1% of the image » | Seuil de surface ; la comparaison (strictement au-delà) est dans video.out_of_range_area_error. | |
| `video.out_of_range_area_error`<br>Erreur si la surface hors tolérance dépasse strictement le seuil (above) ou l'atteint (at_least) | `above` | 5 | « measuring equipment should indicate an “Out-of-Gamut” occurrence only after the error exceeds 1% of the image » | « only after the error exceeds 1% » : erreur strictement au-delà de 1 % (arbitrage de Damien, 28/10/2026). Arte écrit « au moins 1 % » et garde at_least dans son profil. | |
| `video.prefilter`<br>Filtrer le signal avant la mesure des niveaux (dépassements fugitifs) | `true` | 5 | « the use of appropriate filters in all measurement channels is recommended » | R 103 recommande un filtre horizontal à 7 coefficients (1/16 … 1/16) et vertical (1/4, 1/2, 1/4) ; PAD Guard n'applique que [1 2 1]/4 ou [1 4 6 4 1]/16 en horizontal : le noyau n'est pas fixé par la norme dans PAD Guard. | |

## Lu dans la norme, sans valeur dans PAD Guard

| Sujet | Page | Citation | Pourquoi aucune valeur | OK / correction |
|---|---|---|---|---|
| video.prefilter_taps (coefficients du filtre) | 5 | « Horizontal Filter Coefficients: 1/16, 2/16, 3/16, 4/16, 3/16, 2/16, 1/16 » | Paramètre interne ; le noyau de R 103 n'est pas disponible dans PAD Guard (voir video.prefilter). | |
| Plage totale du signal | 5 | « Signals shall not exceed the “Total Video Signal Range”, overshoots that attempt to “exceed” these values may clip. » | 4 - 1019 en 10 bits : codes hors plage totale = codes réservés, contrôlés par la détection de plage, pas par un seuil. | |
| Zone mesurée | 5 | « Signals outside the active picture area shall be excluded from measurement. » | Appliqué par la mesure (zone active), pas de champ. | |

## Champs absents

R 103 ne fixe que les plages de niveaux vidéo, le seuil de surface et le filtrage de mesure.

## Validation

Pour chaque ligne : la valeur correspond-elle au sens du document ? Corrections dans le relevé (`normes/releves/ebu_r103.yaml`), puis `uv run pad-guard releve-norme normes/releves/ebu_r103.yaml`, qui réécrit ce tableau et efface la signature ; relecture complète, puis `uv run pad-guard signer-norme ebu_r103 --par "Vincent"` écrit la signature dans `normes/ebu_r103.yaml`.

Relu par : ____________________  le : ____________
