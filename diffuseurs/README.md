# diffuseurs — cahiers des charges des diffuseurs

Documents techniques des diffuseurs (ce ne sont pas des normes). Ils servent de source aux profils
`profiles/*.yaml` (le champ `meta.source_pdf` pointe dans ce dossier) et, en Phase 4b, à
`pad-checker draft-profile`.

Ce dossier n'est **pas** versionné (`.gitignore`) : documents volumineux, diffusés par les chaînes à
leurs prestataires. Ce fichier liste ce qui est attendu, pour savoir ce qui manque sur une autre machine.

Empreintes : SHA-256 du fichier tel qu'il a été rangé le 23 octobre 2026.

| Fichier | Diffuseur | Document | Version | SHA-256 |
|---|---|---|---|---|
| `Consignes Techniques Globales ARTE G.E.I.E_.pdf` | ARTE G.E.I.E. | Consignes Techniques Globales (94 p.) | **V2-01-03**, septembre 2026 | `2939fd0b530040a42e0305f2c80ea3d9f28c451020bfaf6662cd1c06e935abf0` |
| `Consignes Techniques Globales old ARTE G.E.I.E_.pdf` | ARTE G.E.I.E. | Consignes Techniques Globales, version précédente (114 p.) | V1-07-3, octobre 2024 | `bc9cccf2ef46d28ca7c5d4b0aaa2eae514965bbedcfd79f591de8dd8daa20940` |
| `Annexe technique CDE fichiers HD VT PI 24-01-2023_FR_1.pdf` | France Télévisions | Annexe : normes techniques, Centre de Diffusions et d'Échanges (CDE) | 24/01/2023 | `3cdd935056d18335ddd561c0e61b60c138af317829db42cc44ac39a886481e28` |
| `Process laboratoires - V06082026_vertical.pdf` | France Télévisions | Livraison d'un média au Centre de diffusion et d'échange (CDE) | juillet 2026 (fichier V06082026) | `5868f9e9d767f3916f2ac7a73ce687bb32ddc7b7fb25d1894eedb0898b5139d4` |
| `Microsoft Word - Questions & Réponses Validator+ focus laboratoires - 2024 09 27.pdf` | France Télévisions | Validator+, questions et réponses, focus laboratoires | mise à jour du 27/09/2024 | `7efa5f2534a0bd168b00a44581ac85eddf700c14c5234722ca45d3a2970613a5` |
| `NETFLIX_Knowledge Hub.pdf` | Netflix | Knowledge Hub (non lu : hors périmètre v3) | ? | `53f12b3fe4b4cb4eac792e76198983f6c8c255cadda4ff1e66d07f9454b592dc` |
| `NETFLIX_NonBrandedDeliverySpec_9_3.docx.pdf` | Netflix | Non-Branded Delivery Spec (non lu) | 9.3 d'après le nom | `852fecf2e1222d1823159bce0ad271a5490485e1c49ad5f0144f978f7ac86ac6` |
| `NETFLIX_NonBrandedSpec_&_Delivery_Overview_9_3.docx.pdf` | Netflix | Non-Branded Spec & Delivery Overview (non lu) | 9.3 d'après le nom | `a9893c6cb96297e41fe07ba4a68ed7ac6e652b8f6fa9a0c17fd4d57d4e551f74` |

Remarque : `profiles/arte_hd_sdr.yaml` a été construit sur la version **V2-01-00** des consignes Arte ;
le PDF présent ici est la **V2-01-03**. Les numéros de paragraphe du profil restent à revérifier
sur la V2-01-03, sauf ceux de `format.delivery`, lus dans la V2-01-03 (Phase 4a).
