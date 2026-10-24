# Recette de draft-profile (Phase 4b)

Deux scripts pour mesurer ce que vaut un brouillon extrait par `pad-guard draft-profile`. Ils ne contiennent aucune donnée de diffuseur : les PDF restent dans `diffuseurs/` (non versionné), les brouillons dans `profiles/drafts/`.

## 1. Extraire

```powershell
uv run pad-guard draft-profile "diffuseurs\Consignes Techniques Globales ARTE G.E.I.E_.pdf" --name arte_hd_sdr --broadcaster "ARTE G.E.I.E." --model qwen3-vl:32b-instruct
```

`--broadcaster` sert à exclure les exemples tirés des profils validés de ce même diffuseur. Sans `--model`, l'outil prend `qwen3-vl:32b-instruct`, ou à défaut `qwen3-vl:8b-instruct`. Le temps d'extraction s'affiche à la fin.

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
