# PAD Guard : guide de l'interface

Pour contrôler un PAD sans terminal, à part pour démarrer PAD Guard. Tout se passe sur cette machine : aucun fichier ne quitte l'ordinateur et la page ne charge rien depuis Internet.

## Démarrer

Dans le dossier de PAD Guard (`C:\dev\pad-checker`), ouvrir un terminal et taper :

```
uv run pad-guard ui
```

Le navigateur s'ouvre sur `http://127.0.0.1:8765/`. Laisser le terminal ouvert pendant le travail : le fermer, ou y taper Ctrl+C, arrête PAD Guard. Relancer la commande quand PAD Guard tourne déjà ouvre simplement la page.

## Contrôler un film

1. **Dépôt.** « Parcourir… » ouvre la fenêtre Windows de choix de fichier : choisir le master (.mov ou .mxf). On peut aussi coller le chemin du fichier. Le film n'est pas copié : PAD Guard le lit là où il est. Choisir ensuite le profil de la chaîne (par exemple `arte_hd_sdr`). PAD Guard lit alors le format du fichier ; un fichier refusé (codec, cadence) est signalé avec le motif.
2. **Récapitulatif.** Vérifier les caractéristiques du master, le profil appliqué et ses exigences principales (avec le paragraphe du cahier des charges), et la correspondance des pistes audio : un bouton par piste pour choisir son groupe (VO, VF…). Cocher « Synthèse … par l'IA locale » pour une synthèse rédigée (à relire ; le verdict n'en dépend pas). Puis « Lancer l'analyse ».
3. **Analyse.** La progression montre les étapes, les images mesurées et le temps restant estimé. La lecture du fichier (calcul de son empreinte) et les mesures audio n'ont pas de compteur. Sur un long métrage, compter environ 20 minutes. On peut fermer le navigateur : l'analyse continue, et on la retrouve en rouvrant la page. « Annuler » arrête l'analyse, et le dossier reste incomplet.
4. **Rapport.** Le verdict, le score, les anomalies (filtrables par gravité) et, pour chacune, le timecode, la valeur mesurée, le seuil appliqué, la règle du profil et une vignette quand il s'agit d'une anomalie d'image. « Télécharger le PDF » enregistre le rapport. « Dossier de données » ouvre le dossier de l'analyse dans l'Explorateur.

Avec un profil brouillon, le rapport porte en tête « PROFIL NON VALIDÉ — résultat indicatif » et n'affiche jamais CONFORME.

Les analyses sont rangées par défaut dans `Documents\PAD Guard\analyses\<nom du film>_<date-heure>\`. Le bouton « Réglages » permet de changer ce dossier. Les analyses récentes sont listées sous l'écran de dépôt.

## Créer le profil d'une nouvelle chaîne

Onglet **Profils** :

1. **Nouveau brouillon.** Choisir le PDF du cahier des charges, puis indiquer le diffuseur et un nom de profil (minuscules et _, par exemple `france_tv_hd`), et lancer « Extraire ». L'IA locale (Ollama) lit le document : comptez plusieurs minutes. Le PDF est copié dans `diffuseurs/`.
2. **Relecture.** Pour chaque champ, PAD Guard montre la valeur proposée, la citation du document et sa page (aperçu à droite), la valeur du profil de base et celle de la norme (pour information). Chaque champ demande une décision explicite : accepter, choisir un candidat en cas de conflit, corriger (avec la page et la citation si possible), laisser vide, ou garder la valeur de base. Les renvois du document à une norme (« conforme à EBU R 128 ») se confirment un par un. Les décisions sont enregistrées au fur et à mesure : on peut s'arrêter et reprendre plus tard.
3. **En rouge** : les valeurs invraisemblables, les pages que l'IA n'a pas pu lire en entier (à relire à la main), et les règles bloquantes ou majeures qui ne reposeraient que sur une norme (elles seraient plafonnées à mineur). Ces dernières demandent une confirmation explicite.
4. **Validation.** Saisir son nom, puis « Valider le profil ». Le profil validé est écrit dans `profiles/` et peut désormais produire un verdict CONFORME.

## En cas de problème

- **« Fichier refusé »** : le master n'est pas un ProRes 422 HQ ou un DNxHR HQX à 25 i/s ; le motif exact est affiché.
- **Synthèse IA absente** : Ollama n'est pas lancé ou le modèle n'est pas installé ; le rapport utilise alors la synthèse par gabarit et le signale.
- **La page affiche « jeton de session »** : PAD Guard a été relancé, il suffit de recharger la page (F5).
- **La fenêtre de choix de fichier n'apparaît pas** : elle peut s'ouvrir derrière le navigateur ; sinon coller le chemin du fichier dans le champ prévu.
