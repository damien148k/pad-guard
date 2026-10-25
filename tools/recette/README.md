# Recette de draft-profile (Phase 4b)

Trois scripts pour mesurer ce que vaut un brouillon extrait par `pad-guard draft-profile`. Ils ne contiennent aucune donnée de diffuseur : les PDF restent dans `diffuseurs/` (non versionné), les brouillons dans `profiles/drafts/`.

## 1. Extraire

```powershell
uv run pad-guard draft-profile "diffuseurs\Consignes Techniques Globales ARTE G.E.I.E_.pdf" --name arte_hd_sdr --broadcaster "ARTE G.E.I.E." --model qwen3-vl:32b-instruct
```

`--broadcaster` sert à exclure les exemples tirés des profils validés de ce même diffuseur. Le contexte (`num_ctx`) est calculé sur la plus grosse demande et affiché au début ; pour comparer deux modèles, garder le même (il ne dépend que du PDF et de la consigne, ou le fixer avec `--num-ctx`). Sans `--model`, l'outil prend `qwen3-vl:8b-instruct` (`llm.DEFAULT_MODEL`). Le temps d'extraction s'affiche à la fin.

## 2. Comparer à un profil de référence : `recette.py`

```powershell
uv run python tools\recette\recette.py profiles\drafts\arte_hd_sdr.findings.json profiles\arte_hd_sdr.yaml
```

Le script écrit en Markdown, pour chaque valeur que le profil de référence fixe lui-même (hors valeurs héritées d'une norme), le statut du brouillon :

- identique ;
- **différente non signalée** : c'est l'échec que le critère d'acceptation interdit ;
- en conflit ;
- rejetée ;
- renvoi à une norme ;
- non trouvée.

Il ajoute :

- les valeurs retenues sur des champs que la référence ne fixe pas, à vérifier à la main ;
- pour chaque proposition fausse du modèle, le contrôle qui l'a arrêtée : vocabulaire, nombre, glossaire, conflit…

Code de retour : 1 si une valeur fausse n'est pas signalée, 0 sinon. Pour garder le tableau dans un fichier :

```powershell
uv run python tools\recette\recette.py profiles\drafts\arte_hd_sdr.findings.json profiles\arte_hd_sdr.yaml > recette_arte.md
```

Le profil de référence n'est fiable que s'il est validé (`meta.status: validated`, comme `arte_hd_sdr.yaml`). Contre un profil d'exemple (`france_tv_hd.yaml` tant que Vincent ne l'a pas relu), une valeur « différente » peut être juste : vérifier dans le PDF.

## 3. Rejouer sans le modèle : `replay.py`

Les contrôles de draft-profile sont déterministes. Après un changement des contrôles, du glossaire ou de l'écriture du brouillon, on peut rejouer les réponses brutes enregistrées dans `profiles\drafts\<nom>.llm.jsonl`, en quelques secondes et sans Ollama :

```powershell
uv run python tools\recette\replay.py "diffuseurs\Consignes Techniques Globales ARTE G.E.I.E_.pdf" --name arte_hd_sdr --broadcaster "ARTE G.E.I.E."
```

Les trois fichiers du brouillon sont réécrits. Il faut le même PDF que lors de l'extraction : le script s'arrête si le journal n'a pas assez de lots. Un changement de la consigne (`llm/prompts/`) ou des exemples ne se rejoue pas : il faut une nouvelle extraction.

En PowerShell, si les accents s'affichent mal : `$env:PYTHONIOENCODING = "utf-8"`.

## 4. Comparer des modèles : `banc.py`

Le banc fait tourner plusieurs modèles sur les mêmes PDF avec **la même consigne, le même glossaire, les mêmes exemples et le même contexte**, figés une fois pour toutes. Une modification ultérieure du glossaire ne touche pas le banc. Tout est écrit dans `recette\banc\` (non versionné).

```powershell
# 1. Geler : consigne, glossaire, profils validés (exemples), contexte de chaque PDF, repeat_penalty, commit
uv run python tools\recette\banc.py figer `
  --doc "arte_hd_sdr|diffuseurs\Consignes Techniques Globales ARTE G.E.I.E_.pdf|ARTE G.E.I.E.|profiles\arte_hd_sdr.yaml" `
  --doc "france_tv_hd|diffuseurs\Annexe technique CDE fichiers HD VT PI 24-01-2023_FR_1.pdf|France Télévisions|profiles\france_tv_hd.yaml"

# 2. Lancer : chaque modèle installé, puis libéré (keep_alive 0) avant le suivant ; relançable modèle par modèle
uv run python tools\recette\banc.py lancer --modeles qwen3-vl:8b-instruct qwen3-vl:30b-a3b-instruct qwen3-vl:32b-instruct

# 3. Comparer : recette\banc\comparaison.md
uv run python tools\recette\banc.py comparer
```

- `lancer` vérifie que le gel n'a pas bougé (empreintes de la consigne, du glossaire, des profils et des PDF). Il contrôle aussi que chaque réponse a bien été demandée avec la consigne et le glossaire gelés. Un modèle absent d'Ollama est ignoré, avec la commande `ollama pull` à lancer.
- `comparaison.md` donne, modèle par modèle :
  - le temps ;
  - le nombre de requêtes ;
  - les lots relancés page par page et les pages à la limite ;
  - le tableau de recette contre le profil de référence ;
  - les jetons produits.
- Il indique aussi si les demandes du premier passage étaient identiques pour tous les modèles (`prompt_sha256`). Si ce n'est pas « oui », la comparaison ne mesure pas que le modèle.
- `--docs arte_hd_sdr` dans `lancer` ne traite que ce document. Une nouvelle exécution remplace le résultat du couple modèle/document dans `resultats.json`.
