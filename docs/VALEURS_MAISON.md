# Valeurs maison à relire par Vincent

> **Comment relire** (la signature ne porte que sur ce tableau)
>
> 1. Pour chaque ligne, comparer la valeur à ce qu'elle fait (colonne « Ce que fait la valeur ») : ces valeurs n'ont pas de PDF, ce sont des décisions Lumiris.
> 2. Dans la colonne « OK / correction », écrire `OK`, ou noter la correction (valeur juste et pourquoi).
> 3. Un champ absent du tableau n'est pas soumis à cette relecture.
> 4. Une correction se fait dans `normes/lumiris_maison.yaml` et dans ce tableau (avec l'empreinte ci-dessous, contrôlée par les tests), puis nouvelle relecture.
> 5. Signer : `uv run pad-guard signer-norme lumiris_maison --par "Vincent"` (refusé si `lumiris_maison.yaml` a changé depuis ce tableau).

`normes/lumiris_maison.yaml` fixe ce qu'aucun cahier des charges ne donne : méthodes de mesure, seuils de
détection, gravités par défaut. Ce ne sont pas des normes : elles gardent leur gravité et s'appliquent quand le
profil du diffuseur ne les écrit pas (un profil qui les écrit garde ses valeurs). Toutes portent la mention
« A VERIFIER » : Vincent confirme ou corrige chaque ligne, et la correction se fait dans `lumiris_maison.yaml`
(avec contrôle d'`explain-profile` Arte : le fichier fait partie de ses couches).

Empreinte de `normes/lumiris_maison.yaml` à la génération de ce tableau : `a1e9df753f10df4071cd3e75c3ebdacaf98d5ea7d854ba486fa6cb6b70b645bf`.

## Méthodes et gravités sans document (« décision Lumiris, A VERIFIER Vincent »)

| # | Champ | Valeur | Ce que fait la valeur | OK / correction |
|---|---|---|---|---|
| 1 | `format.unknown_color_tags_severity` | minor | gravité d'une balise de colorimétrie absente ou « unknown » | |
| 2 | `video.bit_depth` | 10 | profondeur de calcul des niveaux (8 bits converti, 12 bits avec les seuils x 4) | |
| 3 | `video.prefilter_taps` | 3 | filtre horizontal avant la mesure des niveaux, quand la norme demande un préfiltre sans longueur | |
| 4 | `audio.silence_dbfs` | -60 dBFS | seuil d'un silence dans le programme | |
| 5 | `audio.silence_max_seconds` | 3 s | durée à partir de laquelle un silence est signalé | |
| 6 | `audio.phase_min_correlation` | -0,3 | seuil de l'opposition de phase (RT 040 p. 11 ne chiffre pas) | |
| 7 | `audio.phase_min_seconds` | 2 s | durée à partir de laquelle l'opposition de phase est signalée | |
| 8 | `audio.exclude_head_tail` | oui | mire, 1 kHz et noirs de tête et de queue exclus des mesures audio (amorce classique) | |
| 9 | `structure.timecode.tolerance_frames` | 0 image | tolérance sur le timecode du début du programme | |
| 10 | `structure.black.y_max` | 68 (10 bits) | luminance maximale d'une image noire (noir légal 64 + 4) | |
| 11 | `structure.black.silence_dbfs` | -60 dBFS | son silencieux pour les noirs de tête et de queue | |
| 12 | `structure.freeze.threshold` | 0,5 (10 bits) | différence moyenne sous laquelle une image est figée | |
| 13 | `structure.freeze.min_seconds` | 2 s | durée à partir de laquelle une image figée est signalée | |
| 14 | `rules.severity.audio_short_term_excursion` | minor | short term maximal des programmes courts (EBU R 128 s1, par R 128) ; ajoutée le 29/10/2026, question ouverte : major si le diffuseur renvoie à la RT 040 ? | |

La ligne 14 vaut pour les profils qui ne fixent pas cette gravité (France TV, m6) ; Arte garde la sienne (minor,
§3.3.2.5) et `lumiris_controle_technique` la sienne (info, confirmée par Damien le 29/10/2026). Sans renvoi du
client à R 128, l'anomalie reste en plus plafonnée à minor (valeur de norme seule).

## Autres choix maison à confirmer (« A VERIFIER avec Vincent »)

| # | Champ | Valeur | Ce que fait la valeur | OK / correction |
|---|---|---|---|---|
| 15 | `rules.merge_gap_seconds` | 0,5 s | deux plages en anomalie plus proches font un seul événement | |
| 16 | `rules.audio_merge_gap_seconds` | 3 s | même regroupement pour true peak, short term, double mono | |
| 17 | `rules.min_event_seconds.freeze` | 2 s | durée minimale d'un événement d'image figée | |
| 18 | `rules.params.levels_major_min_seconds` | 1 s | un dépassement de niveaux ou de gamut d'au moins 1 s est majeur, plus court mineur | |
| 19 | `video.range_detection.reserved_min_frames_pct` | 1 % | part des images aux bornes 4 / 1019 à partir de laquelle le contenu est jugé en plage pleine | |
| 20 | `rules.severity.range_content_mismatch` | major | gravité d'un contenu en plage pleine dans un fichier annoncé en plage légale | |
| 21 | `video.scan_detection` | voir le fichier | paramètres de la détection de peignage, calibrés sur des fixtures et un master Arte | |

Relu par : ____________________  le : ____________
