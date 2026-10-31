# Normes : tableaux de relecture

> **Comment relire** (la signature ne porte que sur ce tableau)
>
> 1. Pour chaque ligne d'un tableau, ouvrir le PDF de la norme (dossier `normes\sources\`) à la page indiquée et comparer la valeur à la citation.
> 2. Dans la colonne « OK / correction », écrire `OK`, ou noter la correction (valeur juste, page, citation).
> 3. Un champ absent du tableau n'est pas contrôlé par la norme.
> 4. Une correction se fait par `releve-norme` (ligne modifiée avec sa citation), puis nouvelle relecture.
> 5. Signer : `uv run pad-guard signer-norme <nom> --par "Vincent"`, refusé si la norme a changé depuis le tableau. Les tableaux sans valeur (« aucun » ci-dessous) se lisent sans signature.

Depuis le 28 octobre 2026 (décision de Damien), les normes internationales ne passent plus par le questionnaire
de `review-profile`. Claude Code relève les valeurs dans le PDF (`normes/releves/<nom>.yaml`), puis
`uv run pad-guard releve-norme normes/releves/<nom>.yaml` vérifie dans le PDF chaque citation et chaque nombre,
écrit la norme et le tableau ci-dessous. **Vincent lit et signe le tableau** (`pad-guard signer-norme`, qui écrit `validated_by`,
`validated_at` et l'empreinte du tableau relu dans `normes/<nom>.yaml`) ; `review-profile` reste pour une
correction ponctuelle.

Une ligne refusée par le code et rien n'est écrit. Le code vérifie que la citation est dans la page, qu'elle parle
du champ, qu'elle contient le nombre, et, dans un tableau, la bonne colonne ; il ne juge pas du sens.

Inventaire des normes citées par les diffuseurs (relevé le 28/10/2026 dans les PDF de `diffuseurs/` ; Arte V2-01-03
et V1-07-3, annexe France TV, Netflix), de la plus citée à la moins citée. « Fichier normes/ » : `écrit` (créé ou
réécrit depuis le relevé), `comparé` (hérité par Arte : le fichier n'est pas réécrit par l'outil, le relevé doit
en donner exactement les valeurs ; une modification se fait à la main, avec contrôle d'explain-profile Arte), `aucun` (la norme ne fixe aucune valeur du profil).

| Norme | Citée par | Tableau | Fichier normes/ | Valeurs |
|---|---|---|---|---|
| EBU R 128 (2023) | Arte, France TV (annexe p. 7), RT 040 | [ebu_r128.md](ebu_r128.md) | comparé (renvoi à s1 déclaré le 28/10) | 4 |
| UIT-R BS.1770-5 | Arte (-4, -2), Netflix (-1), R 128 | [itu_bs1770.md](itu_bs1770.md) | aucun | 0 |
| UIT-R BT.709-6 | Arte, Netflix, RT 040 | [itu_bt709.md](itu_bt709.md) | écrit | 9 |
| UIT-R BT.2020-2 | Arte, Netflix | [itu_bt2020.md](itu_bt2020.md) | écrit | 6 |
| CST-RT-040 V1.2 | Arte V1-07-3, France TV (annexe §I.A) | [cst_rt040.md](cst_rt040.md) | écrit | 29 |
| EBU R 128 s1 (2020) | Arte, RT 040, R 128 | [ebu_r128_s1.md](ebu_r128_s1.md) | écrit | 4 |
| EBU R 103 v3.0 | Arte, RT 040 | [ebu_r103.md](ebu_r103.md) | comparé | 9 |
| EBU Tech 3342 (2023) | Arte, R 128 | [ebu_tech3342.md](ebu_tech3342.md) | aucun | 0 |
| UIT-R BT.2100-3 | Arte | [itu_bt2100.md](itu_bt2100.md) | écrit | 6 |
| UIT-R BT.2408-6 (rapport) | Arte | [itu_bt2408.md](itu_bt2408.md) | aucun | 0 |
| UIT-R BT.1886 | Netflix, RT 040 | [itu_bt1886.md](itu_bt1886.md) | aucun | 0 |

Pas encore relevées :

- **SMPTE ST 2067-21 et ST 2067-201** (IMF, cités par Netflix seulement) : Netflix est hors du périmètre v3 et PAD
  Guard n'analyse pas un paquet IMF ; à faire quand Netflix entrera dans le périmètre.
- **Citées sans PDF dans `normes/sources/`** (aucun relevé possible) : SMPTE 274M, 292M, 299M, 12M-2, ST 2084,
  ST 2086, ST 377-1, 379, 381 ; EBU R 95, R 122, R 37, Tech 3264, 3276, 3299 ; BS.775 ; AES ; AS-10 (AMWA) ;
  BT.601 (déjà signalée manquante dans `normes/sources/README.md`).

`lumiris_maison.yaml` n'est pas une norme (règles internes Lumiris) : pas de relevé ; ses valeurs à relire par
Vincent sont dans [../VALEURS_MAISON.md](../VALEURS_MAISON.md).
