# Relecture critique du cahier des charges « Vérificateur PAD »

Document relu : `cahier_des_charges_verificateur_pad.md` (version du 7 octobre 2026).
Le concept tient la route. Les points ci-dessous sont classés du plus bloquant au plus cosmétique.

---

## 1. Points bloquants (le système ne fonctionnerait pas comme décrit)

### 1.1 NVDEC ne décode pas le DPX
NVDEC/CUDA est un décodeur matériel pour les codecs compressés (H.264, HEVC, AV1, VP9, MPEG-2…). Le DPX est une image **non compressée** : il n'y a rien à « décoder » côté GPU, FFmpeg le lit sur CPU. NVENC (encodage) ne sert à rien ici non plus.
Le vrai goulot d'étranglement est le **débit disque** : un DPX 10-bit fait environ 12 Mo en 2K et environ 50 Mo en 4K, soit environ 300 Mo/s (2K) à 1,2 Go/s (4K) pour lire en temps réel à 25 i/s.
**Conséquence :** la Phase 1 (« décodage ultra-rapide des DPX via la RTX 4090 ») repose sur une prémisse fausse. Il faut la reformuler en « lecture disque + calcul des statistiques parallélisé (multi-cœur, ou GPU via CuPy/PyTorch si besoin) ».

### 1.2 Le format « CRI » est mal identifié et FFmpeg ne le lit pas
« CRI » désigne en pratique le **Cintel Raw Image** des scanners Blackmagic Cintel, pas « Cinema Raw Image » (le RAW Canon, lui, est en .CRM/.RMF). FFmpeg ne sait pas le lire : il faut passer par le SDK Blackmagic ou un rendu DaVinci Resolve.
Surtout, un CRI est un **scan brut** (négatif ou positif non étalonné, pas en Rec. 709) : y mesurer des niveaux PAD n'a pas de sens. À retirer des entrées, ou à limiter à un contrôle d'intégrité du scan.

### 1.3 On contrôle un master intermédiaire, pas le PAD
Un PAD est le fichier **livré au diffuseur** (souvent MXF OP1a XDCAM HD 422 50 Mb/s ou AVC-Intra pour les chaînes françaises, ProRes/IMF pour les plateformes), avec audio, timecode et métadonnées dans le conteneur. Le cahier ne prend en entrée que des suites DPX.
Plusieurs contrôles listés n'ont alors pas de sens sur du DPX : la mire de barres, le décompte et les noirs de tête sont ajoutés au moment du conditionnement PAD, pas dans le master restauré.
**À trancher :** soit l'outil contrôle le master DPX (« pré-contrôle PAD »), soit il contrôle le fichier PAD final (et il faut ajouter MXF/MOV/ProRes en entrée). Les deux sont utiles, mais pas avec la même liste de contrôles.

### 1.4 Les seuils 64/940 ne s'appliquent pas directement au DPX
Les seuils 64–940 (10-bit) concernent le **Y'CbCr en plage légale**. Un DPX est en **RGB**, souvent en pleine échelle (0–1023), voire en **log Cineon** (noir à 95, blanc à 685). Mesurés tels quels, les chiffres sont faux.
Il faut spécifier : la matrice de conversion RGB→Y'CbCr (BT.709), la plage d'entrée (pleine/légale) et le traitement des DPX log (refus ou conversion via LUT). L'en-tête DPX (champs transfert/colorimétrie) doit être lu pour le détecter.
En 12-bit, les seuils deviennent 256 et 3760 : le cahier ne le dit pas.

### 1.5 « Précision mathématique 100 % » contredit la décision par IA
Un LLM n'est pas déterministe : deux exécutions peuvent donner deux verdicts différents. Si l'IA décide de ce qui est « artistique » ou « défaut », le statut CONFORME/NON-CONFORME n'est plus reproductible ni opposable au diffuseur.
**Recommandation :** le verdict et le score sont calculés par des **règles déterministes** (couche 2). L'IA ne fait que rédiger la synthèse et **suggérer** une qualification (« probablement artistique ») que Vincent valide.

---

## 2. Erreurs techniques

| Passage | Problème | Correction |
|---|---|---|
| « RTX 4090 / 4090 Ti » | La 4090 Ti n'est jamais sortie. | RTX 4090 (ou génération suivante). Le GPU est d'ailleurs peu sollicité (voir 1.1), sauf pour un LLM local. |
| « 940 … / 1.0V sur l'oscilloscope » | Le blanc 100 % correspond à **700 mV**. 1 V est l'amplitude totale crête-sync en analogique. | « 940 en 10-bit / 100 % / 700 mV ». |
| « 0 % IRE » | L'IRE est une unité NTSC. En Europe on parle de mV ou de %. | « 0 % / 0 mV ». |
| Seuils stricts < 64 et > 940 | La norme EBU R103 tolère de **-1 % à +103 %** sur la luminance et de **-5 % à +105 %** sur les composantes RGB, après filtrage. Un seul pixel de grain hors plage déclencherait une alerte : sur un film restauré, ce serait presque chaque image. | Seuils paramétrables par chaîne, plus un **seuil de surface** (ex. alerte si > 1 % des pixels sont hors plage). `signalstats` fournit `YLOW`/`YHIGH` (percentiles) et `BRNG` (proportion de pixels hors plage), plus robustes que `YMIN`/`YMAX`. |
| Gamut « hors Rec. 709 ou Rec. 2020 » | Ambigu. En HD SDR, la légalité de gamut se contrôle sur les **composantes RGB** (R103), pas sur des chromaticités. `signalstats` ne fait pas ce contrôle : il faut le calculer en NumPy. Et Rec. 2020 implique souvent de l'UHD/HDR (PQ/HLG), avec d'autres seuils. | Un profil par livrable : HD SDR Rec. 709, ou UHD HDR Rec. 2020 avec ses propres règles. |
| `ebur128` : -23 LUFS / -1 dBTP | Valeurs EBU R128 génériques. En France, la recommandation CST-RT-017 impose **-23 ±1 LU et -3 dBTP**. Netflix exige -27 LKFS (dialogue) et -2 dBTP. Coder ces valeurs en dur contredit la couche 3, censée lire la norme du client. | Valeurs dans le profil de la chaîne. Ajouter la **LRA** (plage de loudness), souvent exigée. |
| « Échantillonnage strict toutes les X frames » | Incompatible avec « journaliser **chaque** frame » : un flash d'une image passerait inaperçu. | Analyse de toutes les images par défaut. L'échantillonnage n'est qu'un mode de prévisualisation rapide. |
| Filtre `oscilloscope` | Dans FFmpeg, c'est une sonde de ligne, pas un moniteur forme d'onde. | Utiliser `waveform` (et `vectorscope` pour la chroma). |

---

## 3. Incohérences internes

- **Couche 3 ou rapport :** la couche 3 doit « comparer avec le cahier des charges de la chaîne », mais les seuils sont codés en dur dans les modules 2 et 5. Il faut un **fichier de profil par chaîne** (YAML/JSON : seuils vidéo, audio, structure de tête, TC de départ). L'IA peut aider à rédiger ce profil à partir du PDF du diffuseur, avec relecture humaine, mais ne doit pas le réinterpréter à chaque analyse.
- **Le JSON est trop gros pour un LLM :** 90 min à 25 i/s font 135 000 images, avec une dizaine de valeurs chacune. Il faut une étape d'**agrégation en événements** (« plage TC A–B : blancs > 940 sur 3 % de l'image, max 1002 ») avant de passer quoi que ce soit au LLM.
- **Distinguer artistique et défaut sur des chiffres seuls :** un LLM ne peut pas voir un projecteur dans le cadre à partir d'un JSON. Il faut lui transmettre des **vignettes** des images concernées (modèle vision). Par ailleurs, pour le diffuseur, un blanc illégal reste illégal même s'il est voulu : la qualification « artistique » ne doit pas transformer un NON-CONFORME en CONFORME.
- **Audio :** le DPX ne contient pas d'audio. « Fichier lié » doit être précisé : WAV BWF ? Combien de pistes ? Quelle configuration (stéréo, 5.1, version internationale) ? Comment est-il synchronisé (TC BWF) ?
- **Exemples de chaînes :** le module 3 cite Arte, le rapport cite France Télévisions. C'est sans gravité, mais cela confirme qu'il faut gérer plusieurs profils.
- **Score de conformité global :** il n'est défini nulle part. Même question pour les niveaux de **gravité** du tableau. Il faut une règle explicite (ex. : bloquant / majeur / mineur, et une seule anomalie bloquante entraîne NON-CONFORME).
- **« Bobine 3 » :** la gestion multi-bobines (plusieurs dossiers DPX, continuité du TC entre bobines) n'est pas spécifiée.
- **« Vincent »** apparaît sans être présenté. Ajouter une section « Utilisateurs » (rôle, niveau technique, attentes).

---

## 4. Contrôles manquants pour un vrai contrôle qualité PAD

- Format : résolution, cadence (25p ; attention au passage 24 → 25 pour le film), rapport d'image, progressif ou entrelacé, durée totale.
- **PSE (épilepsie photosensible, test Harding/Ofcom)** : exigé par beaucoup de diffuseurs, et proche de la détection de flashs déjà prévue.
- Images figées, images noires isolées, images dupliquées ou manquantes dans la séquence DPX (trou de numérotation, ruptures de TC).
- Zones de sécurité (titres et sous-titres dans le cadre « title safe »).
- Audio : silences, inversion de phase, mapping des pistes, clics.
- Intégrité des fichiers : DPX tronqués ou corrompus, en-têtes incohérents d'une image à l'autre.

---

## 5. Exigences non fonctionnelles absentes

- **Performance cible chiffrée** (ex. « 90 min en 2K analysées en moins de 45 min ») au lieu de « temps réel ou *faster-than-realtime* ».
- **Confidentialité :** envoyer des données ou des images de films clients à une API externe (OpenAI) peut violer les contrats. Il faut privilégier le modèle local, ou le rendre obligatoire. À noter : GPT-4o est un modèle ancien en 2026, citer plutôt « un LLM compatible » sans figer le modèle.
- **Mémoire GPU partagée :** un LLM local sous Ollama et d'éventuels calculs GPU partageront les 24 Go de VRAM.
- **Validation :** il faut un jeu de fichiers de référence (conformes et non conformes connus) pour recetter l'outil, plus des critères d'acceptation par module.
- Traçabilité : version de l'outil et du profil utilisés, inscrite dans le rapport.

---

## 6. Coquilles

- « Résumé **Éxécutif** » → « Résumé **Exécutif** ».
- « Numpy » → « NumPy ».
- « Prêt À Diffuser » : l'usage courant est « Prêt à Diffuser ».
- « 100/0/75/0 ou 100/0/100/0 » : à garder, mais préciser que ce sont les barres EBU (75 %) et 100 %, et ajouter la durée et la position attendues (ex. 30 s de barres + 1 kHz à -18 dBFS).
- Le TC de départ « 10:00:00:00 » est celui du programme. La tête (mire, décompte) commence avant, souvent vers 09:59:30:00. À préciser dans le profil.

---

## 7. Jalons proposés (réordonnés)

1. **Profils et ingest :** lecture DPX (en-têtes, colorimétrie, TC, détection des trous de séquence), plus un format de profil de chaîne.
2. **Moteur de mesures déterministe :** `signalstats` + calculs NumPy (gamut RGB, surfaces hors plage), `ebur128` sur l'audio, sortie JSON par image.
3. **Agrégation en événements et verdict par règles :** score, gravité, rapport Markdown/PDF **sans IA**. À ce stade, l'outil est déjà utilisable et opposable.
4. **Couche IA :** synthèse rédigée, qualification suggérée à partir de vignettes, aide à la création des profils depuis les PDF des diffuseurs.
5. **Interface** Gradio/Streamlit.

Avec cet ordre, l'outil apporte de la valeur dès l'étape 3, et l'IA arrive en complément au lieu d'être une dépendance du verdict.
