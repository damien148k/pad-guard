# pad-checker : résumé pour la conception de l'interface

## À quoi ça sert

pad-checker vérifie automatiquement qu'un film restauré respecte le cahier des charges technique d'un diffuseur (« Prêt à Diffuser », PAD) avant livraison. Il analyse le fichier image par image et échantillon par échantillon, compare les mesures à un **profil** de chaîne, et produit un **rapport** qui dit CONFORME ou NON-CONFORME, avec chaque anomalie localisée (timecode et numéro d'image) et une vignette quand c'est utile.

Utilisateur final : **Vincent**, responsable technique chez Lumiris Production. Il n'est pas développeur. Il veut déposer un fichier, choisir une chaîne, et lire un rapport clair.

## Entrées

- **Le film** : master ProRes 422 HQ ou DNxHR HQX, 1080 (progressif ou entrelacé), 25 i/s aujourd'hui. Jusqu'à 120 Go et environ 1 h 30 de programme.
- **Le profil de chaîne** : un fichier YAML par diffuseur (par exemple Arte HD SDR, France TV en brouillon). Il contient les seuils, la structure attendue (amorce, timecode de départ, noirs) et les règles de gravité. Chaque valeur cite son paragraphe du cahier des charges.
- **La correspondance audio** : quelle piste est la VO, la VF, etc. (par exemple `VO:1-2,VF:3-4`), donnée en ligne de commande.
- **Plus tard** : le PDF du cahier des charges d'un diffuseur, dont l'IA locale tirera un profil brouillon à valider par Vincent (Phase 4b).

## Sorties

- **Un rapport PDF** (et Markdown) : en-tête (fichier, empreinte SHA-256, profil et sa version, date), statut, score, synthèse, tableau des contrôles de format et de structure (attendu / mesuré / OK ou ÉCHEC), mesures audio par groupe de pistes, tableau des anomalies classées par gravité, annexes (courbes de luminance et de loudness dans le temps), vignettes.
- **Des fichiers de données** : `probe.json`, `measurements`, `events.json`, `effective_profile.json`, pour retraiter sans tout recalculer.

## Gravités

- **Bloquant** : fait échouer le PAD (format, loudness, timecode de départ, etc.).
- **Majeur** : à corriger, déclenche NON-CONFORME (blancs ou noirs hors tolérance, flashs, gamut, LRA).
- **Mineur** : toléré, signalé (silences, images dupliquées, règles déduites).
- **Info** : pour information.

## Principes à respecter dans l'interface

1. **Le verdict est calculé par des règles, jamais par une IA.** L'interface affiche le verdict tel quel.
2. **Aucune valeur de norme n'est codée en dur dans l'interface.** Tout vient du profil.
3. **Un profil en brouillon ne produit jamais « CONFORME »** : le rapport affiche « PROFIL NON VALIDÉ, résultat indicatif ».
4. **Rien ne sort de la machine.** L'IA, quand elle arrivera, tournera en local (Ollama).
5. **L'interface ne contient aucune logique métier.** Elle appelle la CLI ou les mêmes fonctions Python.
6. **Les anomalies doivent être vérifiables** : timecode, numéro d'image, valeur mesurée, seuil appliqué, vignette.

## Commandes existantes

```
pad-checker analyze <film> --profile profiles/arte_hd_sdr.yaml --out <dossier> --audio-map "VO:1-2,VF:3-4"
pad-checker rerun <dossier> --from structure|rules|report [--profile ...]
pad-checker report <dossier>
pad-checker explain-profile <profil.yaml>
pad-checker validate-profile <profil.yaml>
```

Une analyse complète d'un master de 1 h 30 prend environ 20 minutes sur la station de Damien (Ryzen 9 5950X, sans GPU). `rerun` permet de relancer les règles ou le rapport sans refaire les mesures.

## Où en est le projet (24/10/2026)

- Phases 0 à 3 terminées et validées par Vincent sur un vrai master Arte.
- Phase 4a terminée : normes internationales séparées du profil diffuseur, héritage, profil effectif, règle « le cahier des charges du client fait foi ». Sur le vrai master, résultats identiques avant et après.
- Phase 4b en préparation : `draft-profile` (lecture IA locale du PDF diffuseur, chaque valeur avec sa citation, validation humaine).
- Phase 4c : synthèse IA dans le rapport (Ollama uniquement).
- **Phase 5 : interface locale**, c'est-à-dire ce pour quoi tu conçois l'écran.
- Phases 6 et 7 : formats étendus (cadences autres que 25 i/s, UHD) puis HDR.

## Ce que l'interface devrait permettre à Vincent

1. Glisser le film (et plus tard le PDF du diffuseur) dans une zone de dépôt.
2. Choisir un profil dans une liste, avec son statut (validé ou brouillon) et son diffuseur.
3. Indiquer la correspondance audio (VO, VF) avec une aide visuelle : quelle piste est quelle langue.
4. Lancer l'analyse et suivre la progression (images traitées sur le total, temps estimé).
5. Lire le verdict en grand, puis la liste des anomalies : filtrer par gravité, cliquer un timecode pour voir la vignette.
6. Télécharger le rapport PDF et le dossier de données.
7. Pour un brouillon de profil : un écran de validation champ par champ (valeur, page et citation du document, valeur de la norme pour comparaison) qui ne valide qu'après un nom.
8. Rien à installer côté Vincent : l'outil tourne sur la machine locale.

## Question ouverte pour toi

Le choix du framework d'interface (Gradio ou Streamlit) n'est pas encore tranché. Je le recommande avec la décision suivante : une interface locale minimale qui appelle la CLI, pour ne pas dupliquer la logique métier.
