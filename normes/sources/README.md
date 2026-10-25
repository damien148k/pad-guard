# normes/sources — documents sources des normes

Ce dossier contient les PDF des normes internationales dont sont tirées les valeurs de `normes/*.yaml`.
Il n'est **pas** versionné (`.gitignore`) : documents volumineux, et pour certains sous licence (SMPTE, ISO).
Ce fichier liste ce qui est attendu, pour savoir ce qui manque sur une autre machine.

Empreintes : SHA-256 du fichier tel qu'il a été rangé le 23 octobre 2026.
« Non lu » : document hors périmètre v3 (IMF, Blu-ray, FIAF, IPI), pas ouvert ; titre tiré du nom de fichier.

## AUDIO — utilisés par `normes/ebu_r128.yaml`

| Fichier | Document | Version | Origine | SHA-256 |
|---|---|---|---|---|
| `AUDIO/r128.pdf` | EBU R 128, Loudness normalisation and permitted maximum level of audio signals | novembre 2023 | EBU (tech.ebu.ch, gratuit) | `2bd911fc3cd3e53351fcb47039e33aa5cd2ac9e9175a122c24b0308a69ee161c` |
| `AUDIO/r128s1.pdf` | EBU R 128 s1, Loudness parameters for short-form content | août 2020 | EBU | `1f6eefd407b56f07b16e8f1c61cc3d63502fe85f1362a806b57bed0494114445` |
| `AUDIO/r128s2.pdf` | EBU R 128 s2, Loudness in streaming | novembre 2023 | EBU | `034b282333a5c9db6070a9a740c0b6d327ef27d31850824d58cfac4965cb3e9c` |
| `AUDIO/tech3341.pdf` | EBU Tech 3341, Loudness metering: « EBU Mode » metering | novembre 2023 | EBU | `1a350233a0db04d90237e083255d0ffb44fd991765a810d1021b6297cc4fb97d` |
| `AUDIO/tech3342.pdf` | EBU Tech 3342, Loudness range | novembre 2023 | EBU | `8b9fcfd268e1eea067cbc990938752ee47377904d7180c327f79b19bf2c806c3` |
| `AUDIO/tech3343.pdf` | EBU Tech 3343, Guidelines for production of programmes in accordance with EBU R 128 | novembre 2023 | EBU | `be6986f19fbf361de24c524d0174f9d6c1dcd429af93ef8541a45cf530ceac8d` |
| `AUDIO/tech3344.pdf` | EBU Tech 3344, Practical guidelines for distribution systems in accordance with EBU R 128 | v1.1, octobre 2011 | EBU | `56dcd6ea40bbc24a4b768820237f927a02fda6226750a1a0fa313370a52e885c` |
| `AUDIO/tech3401.pdf` | EBU Tech 3401, Guidelines for radio production and distribution in accordance with EBU R 128 | novembre 2023 | EBU | `ac571db62e4eb8c9bbc74680910730b286adec89382002fef95a52260aa0ad25` |
| `AUDIO/Recommendation ITU-R BS.1770-5 (11_2023) Algorithms to measure audio programme loudness and true-peak audio level.pdf` | ITU-R BS.1770-5 | 11/2023 | UIT (itu.int, gratuit) | `615c01958eb5b4eda821c55da77c89376acb782b4a1fef89ccd1f3d7aaf1f857` |

## TV — utilisé par `normes/ebu_r103.yaml` (R103) et `normes/itu_bt709.yaml` (BT.709) ; BT.2100 (plage pleine) par le décodage ; les autres serviront à la phase 7

**Manque : ITU-R BT.601** (SD, matrice Kr 0,299 / Kb 0,114). Les coefficients usuels sont utilisés en attendant (`formats.MATRICES`, marqués A VERIFIER) : ajouter le PDF (gratuit à l'UIT) dans `TV/` et sa ligne ici.

| Fichier | Document | Version | Origine | SHA-256 |
|---|---|---|---|---|
| `TV/r103.pdf` | EBU R 103, Video signal tolerance in digital television systems | version 3.0, mai 2020 | EBU | `6859c50c2a854d7794540ca534905c4ecda829de3040fbf7985af0aa0c1ec2e5` |
| `TV/Parameter values for the HDTV standards for production and international programme exchange.pdf` | ITU-R BT.709-6 | 06/2015 | UIT | `460b9e95d473b4344bd468e2e9f9739e03319e74038a5a5e87ba76fa62afdd60` |
| `TV/RECOMMENDATION ITU-R BT.1886 - Reference Electro-Optical Transfer Function (EOTF) for flat panel displays used in HDTV studio production.pdf` | ITU-R BT.1886 | 03/2011 | UIT | `796e4267c81907253a9792b2c7b0aba9d104128f2aa2ad9ba0ca043175a74671` |
| `TV/R-REC-BT.2020-2-201510-I!!PDF-E.pdf` | ITU-R BT.2020-2 | 10/2015 | UIT | `eed65cf78c95923964c5420ac4f60d1c83f68823c7a71b05a5e31818ebd03374` |
| `TV/R-REC-BT.2100-3-202502-I!!PDF-E.pdf` | ITU-R BT.2100-3 | 02/2025 | UIT | `f0668803dce2cd67e3780efbe97494c776b7d6b680733c8237fee364f2d412c3` |
| `TV/cst-rt-040-tv-2016-pad_fichiers_editeurs_v1.2.pdf` | CST-RT-040-TV, Recommandation technique PAD fichiers éditeurs (source de `normes/cst_rt040.yaml`, renvoi de l'annexe France TV §I.A) | V1.2, 2016 | CST | `c3c2a86b10aed7c7b068b5b775d9f17366ebedfcfe619316f6dd793a78480b3c` |

## HDR_COULEUR — phase 7

| Fichier | Document | Version | Origine | SHA-256 |
|---|---|---|---|---|
| `HDR_COULEUR/High dynamic range television for production and international.pdf` | Report ITU-R BT.2390-8 | 02/2020 | UIT | `f0284abef7bf30ba7a8059a11f28b5506eb5ae4bf55f7d095fa47618fcf13948` |
| `HDR_COULEUR/REPORT  ITU-R  BT.2408-6 – Guidance for operational practices in HDR television production.pdf` | Report ITU-R BT.2408-6 | 03/2023 | UIT | `5e17d5bad48585f6f5c8a170c0bc929ee1f4d0da9462071982569c0d70eb5f3d` |

## CST

| Fichier | Document | Version | Origine | SHA-256 |
|---|---|---|---|---|
| `CST/CST-RT-021_Fichier-Mezzanine_CST-RT-021-C-2013-Part2-FR-Mezzanine-format-specification-XY.pdf` | CST-RT-021 part 2 (même titre que `TV/cst-rt-021…`, fichier différent) | 2013 | CST | `aeffc523cdd00af7b00c3ac5f7a00a6142b2ab0d5c43905951a41da965d9b286` |

## Hors périmètre v3 (non lus)

| Fichier | Origine | SHA-256 |
|---|---|---|
| `IMF_PLATEFORMES/SMPTE OV 2067-0_2021 - Interoperable Master Format.pdf` | SMPTE (payant) | `84be3eab2533e8ba2611f16506dfc3b75f59b33817f021f6c1a9fb69dc48e79c` |
| `IMF_PLATEFORMES/ST 2067-2, Interoperable Master Format (IMF) — Core Constraints.pdf` | SMPTE (payant) | `e589723b3ab4d46623f58ea0e101cd28db65fce0119237d975fac10de153e656` |
| `IMF_PLATEFORMES/ST 2067-3, Interoperable Master Format (IMF) — Composition Playlist.pdf` | SMPTE (payant) | `9b47e269067da74b55f1fd29419fbfa41a46de5db4a8a941defc22214bb0d999` |
| `IMF_PLATEFORMES/ST 2067-5, Interoperable Master Format (IMF) — Essence Component.pdf` | SMPTE (payant) | `193dc7e98b671af9ef00a5db97fad9c6f432d8714c97e6987d9da775aff54707` |
| `IMF_PLATEFORMES/ST 2067-8, Interoperable Master Format (IMF) — Common Audio Labels.pdf` | SMPTE (payant) | `6449955e566987f238ea8aa1fbd1ff73eab0d7015e63ed494687fb57f4939dad` |
| `IMF_PLATEFORMES/ST 2067-9, Interoperable Master Format (IMF) — Sidecar Composition Map.pdf` | SMPTE (payant) | `bd443ebc7afb26d367a320809f397ae0dbe8ef65f44db4b82ca6b65259791c40` |
| `IMF_PLATEFORMES/ST 2067-21, Interoperable Master Format (IMF) — Application #2E.pdf` | SMPTE (payant) | `69c20a2bc83be584e6ff6ac18e89b2cea6882782296a04319c02e3554ee55aa6` |
| `IMF_PLATEFORMES/ST 2067-30, Interoperable Master Format (IMF) — Application #3.pdf` | SMPTE (payant) | `360afe764f277c94622f366383de7a9ac64b8d5e19d27f365e223756cbf0c26b` |
| `IMF_PLATEFORMES/ST 2067-40, Interoperable Master Format (IMF) — Application #4 Cinema Mezzanine.pdf` | SMPTE (payant) | `481cf15b6cc36f771e7fa38971e828513a3500d4be08e960d6424b45a260f6b7` |
| `IMF_PLATEFORMES/ST 2067-50, Interoperable Master Format (IMF) — Application #5 ACES.pdf` | SMPTE (payant) | `006b073b4d17b6dd2cb8b4c6554a7a2d786aa026521a5489015c34e88e3cd4a9` |
| `IMF_PLATEFORMES/ST 2067-60, Interoperable Master Format (IMF) — Application #6 UHDTV Program Workflow (AVC).pdf` | SMPTE (payant) | `9149a6748a1d0ef41dc589a9e11c85503b8374498a08bdbd42530c2f0b8650a7` |
| `IMF_PLATEFORMES/ST 2067-70, Interoperable Master Format (IMF) — Application SMPTE ST 2019-1 (VC-3).pdf` | SMPTE (payant) | `dfda8336c20f42a2bfeea143f04e7b29b0399693e3e55ce228e675a26d1d1416` |
| `IMF_PLATEFORMES/ST 2067-71, Interoperable Master Format (IMF) — Application SMPTE ST 2117-1 (VC-6).pdf` | SMPTE (payant) | `7c7e1c9deea7c66cb17da9b19ece4d5b0b1abb5313046ca96fa6c99f7b9ac606` |
| `IMF_PLATEFORMES/ST 2067-100, Interoperable Master Format (IMF) — Output Profile List.pdf` | SMPTE (payant) | `d339a77b13974ef8863c14600dd1e20a7171923b00f96c3a14b4723ea9cd8a7d` |
| `IMF_PLATEFORMES/ST 2067-101, Interoperable Master Format (IMF) — Common Image Definitions and Macros.pdf` | SMPTE (payant) | `23fdee4dc7cbdcbadcde18d469e51ac86b16edcac604ad27d659eced05cb6d79` |
| `IMF_PLATEFORMES/ST 2067-102, Interoperable Master Format (IMF) — Common Image Pixel Color Schemes.pdf` | SMPTE (payant) | `12fd466f69a6433a533cfe41387b161a32927fc1d54dfc7e4b8fd04493b4b479` |
| `IMF_PLATEFORMES/ST 2067-103, Interoperable Master Format (IMF) — Common Audio Definition and Macros.pdf` | SMPTE (payant) | `6145a51a68d70f81d8683e921a6ad67ef7506cbc945d7b89678763bc9b75ce8b` |
| `IMF_PLATEFORMES/ST 2067-200, Interoperable Master Format (IMF) — Dynamic Metadata for Color Volume Transform (DMCVT) Plug-in.pdf` | SMPTE (payant) | `b71f397e41da2f6faeb8f0994aa9775fc289e3805ad5180d4d55c3d6c8538fb4` |
| `IMF_PLATEFORMES/ST 2067-201, Interoperable Master Format (IMF) — Immersive Audio Bitstream Level 0 Plug-in.pdf` | SMPTE (payant) | `a5a6650c538dd2458c5f9a323006f2228ca42c2bbba7c91ad9cf7c1d1fa3e3b4` |
| `IMF_PLATEFORMES/ST 2067-202, Interoperable Master Format (IMF) — Isochronous Stream of XML Documents (ISXD) Plug-in.pdf` | SMPTE (payant) | `ecc10ae5778d2798399003006687e49cf4107bee8dc753855b38d8c7dc64f748` |
| `IMF_PLATEFORMES/ST 2067-203, Interoperable Master Format (IMF) — Audio with Frame-based S-ADM Metadata Plug-in.pdf` | SMPTE (payant) | `eb38ea049435379efb45decce888aa5067eabaeacd0d21f82fdbfcca59086cd3` |
| `IMF_PLATEFORMES/ST 2067-204, Interoperable Master Format (IMF) — Audio with ADM Metadata Plug-in.pdf` | SMPTE (payant) | `7399f5ff6e5f0935df02e0b5131c52dd1a2944f6082024b477cc569bf1b4bd57` |
| `IMF_PLATEFORMES/ST 2067-206, Interoperable Master Format (IMF) — Event-based, Text-based Metadata Plug-in.pdf` | SMPTE (payant) | `c22aacbb43c770f6604e7e93119364ab06c0bb0b81d7841e9dc68b52990ced17` |
| `BLURAY/Microsoft Word - BD-ROMwhitepaper20051123clean.doc.pdf` | Blu-ray Disc Association (livre blanc BD-ROM, 2005 d'après le nom) | `83061b0c79dcc87dcc28329d82d2f35fe20edf7f66f50efacbbaba32188cdb76` |
| `FIAF NORMES/FIAF TECHNICAL COMMISSION RECOMMENDATION.pdf` | FIAF | `455a8fa005e2f448224142e8a1a44396e7a154c855090b12a115a56a2c38d12b` |
| `FIAF NORMES/International Federation of Film Archives 7.pdf` | FIAF | `8e31a9c235ea0e17f052aa41b2958cbc587aedeaacdcd01b7973b5ce025ce300` |
| `IPI/methodology_guidebook_all.pdf` | Image Permanence Institute | `7918b6b37454d7a71f3a2ca684f6bc480bc9c537fbdb85fc689893489725bdd6` |

## Retirés lors de l'audit du 25 octobre 2026

Archivés dans `_archives/normes_sources/` (même sous-dossier), ou supprimés quand c'était un doublon.

| Fichier | Sort |
|---|---|
| `AUDIO/RECOMMENDATION ITU-R BS.1770-2 - Algorithms to measure audio programme loudness and true-peak audio level.pdf` | archivé (remplacé par BS.1770-5) |
| `TV/Template BR_Rec_2005.dot.pdf` | supprimé (même document que R-REC-BT.2020-2) |
| `TV/cst-rt-021-c-2013-part2-fr-specificationformatmezzanine-3.pdf` | archivé (copie de CST/CST-RT-021…) |
| `TV/ISO-26428-19-2011.pdf` | archivé (aperçu incomplet) |
| `IMF_PLATEFORMES/OV 2067-0, Interoperable Master Format (IMF) — Interoperable Master Format.pdf` | supprimé (même document que SMPTE OV 2067-0_2021) |
| `IMF_PLATEFORMES/ST 2067-20, Interoperable Master Format (IMF) — Application #2.pdf` | archivé (IMF App #2, retirée en 2020) |
| `IMF_PLATEFORMES/st2067-20-withdrawal2020.pdf` | archivé (avec ST 2067-20) |
| `BLURAY/Slide 1.pdf` | archivé (origine inconnue) |
