# Recette de la Phase 6 (25 octobre 2026)

Fichiers réels : code du commit `0b55d80` (sources figées) ; tableau des formats : code du commit `b641b3b` (refus HDR compris). Machine de développement (AMD Ryzen 9 5950X, 16 cœurs, Windows 11). Les fixtures sont générées par `tests/fixtures/make_fixtures.sh` ; chaque ligne est une analyse complète (`analyze`) avec le profil `lumiris_controle_technique` (aucun refus pour une raison de profil). « Lu » : ffprobe et PyAV ouvrent le fichier ; « Analysé » : mesures, structure, règles et rapport écrits.

## Fichiers réels

| Fichier | Profil | Lu | Analysé | Résultat | Durée |
|---|---|---|---|---|---|
| Master Arte 1080i50 ProRes HQ (120 Go, drapeau tb, images progressives) | `arte_hd_sdr` 1.2 | oui | oui | NON-CONFORME, 56 événements **identiques à l'image près** à ceux de la Phase 4a (seule la source de la règle des deux anomalies de niveaux change) ; audio identique à l'octet ; mesures vidéo identiques hors nouveaux champs de trame | 30 min (empreinte SHA-256 comprise) |
| 50p « destroyed » ProRes HQ 1080p50 (235 Go, TC base 50) | `arte_hd_sdr` 1.2 | oui | oui, 261 916 / 261 916 images, aucune erreur de décodage | NON-CONFORME : 217 bloquantes (loudness -0,4 LUFS, 215 dépassements de true peak, TC 00:00:00:00), 24 majeures, 80 mineures | 34 min |
| ASTERIX CLEO (DNxHR HQ 8 bits 2048x1556 23,976, TC base 24) | `arte_hd_sdr` 1.2 | oui | oui, 8 257 / 8 257 images | NON-CONFORME ; anomalies de format, pas de refus : cadence 24000/1001, 8 bits, 2048x1556, drapeau de balayage absent ; TC 00:00:00:00 | 3 min 49 |
| ASTERIX CLEO | `lumiris_controle_technique` | oui | oui | Rapport technique : 2 majeures (PSE), 3 mineures (images dupliquées), 33 informations (audio) | 2 min 11 |

## Formats (fixtures)

| Format testé | Fixture | Lu | Analysé | Refusé (motif) | Remarques |
|---|---|---|---|---|---|
| ProRes 422 HQ, MOV, 1080p25 | `ok_prores.mov` | oui | oui (code 0) | non | prores HQ, 1920x1080, 25/1, 4:2:2 10 bits ; 500/500 images, 0 erreur(s) ; anomalies : audio_loudness, audio_silence, freeze |
| ProRes 422 LT, MOV | `wrong_codec.mov` | oui | oui (code 0) | non | prores LT, 1920x1080, 25/1, 4:2:2 10 bits ; 500/500 images, 0 erreur(s) ; anomalies : audio_loudness, audio_silence, freeze |
| ProRes 4444 + alpha (12 bits 4:4:4), MOV | `fmt_prores4444_alpha.mov` | oui | oui (code 0) | non | prores 4444, 640x360, 25/1, 4:4:4 12 bits ; 50/50 images, 0 erreur(s) ; anomalies : alpha_channel, gamut |
| DNxHR HQX, MXF OP1a | `ok_dnxhr.mxf` | oui | oui (code 0) | non | dnxhd DNXHR HQX, 1920x1080, 25/1, 4:2:2 10 bits ; 500/500 images, 0 erreur(s) ; anomalies : audio_loudness, audio_silence, freeze |
| DNxHR HQX, MXF OP-Atom | `fmt_opatom.mxf` | oui | oui (code 0) | non | dnxhd DNXHR HQX, 320x180, 25/1, 4:2:2 10 bits ; 50/50 images, 0 erreur(s) ; anomalies : audio_not_analysed, gamut |
| DNxHR HQ 8 bits 2048x1556 23,976 (scan) | `fmt_dnxhr_hq_2k.mov` | oui | oui (code 0) | non | dnxhd DNXHR HQ, 2048x1556, 24000/1001, 4:2:2 8 bits ; 96/96 images, 0 erreur(s) ; anomalies : aucune |
| DNxHR 444 R'G'B', MOV | `fmt_dnxhr444_rgb.mov` | oui | oui (code 0) | non | dnxhd DNXHR 444, 640x360, 25/1, rgb 10 bits ; 50/50 images, 0 erreur(s) ; anomalies : format |
| XAVC / AVC-Intra (H.264 High 4:2:2 Intra 10 bits), MP4 | `fmt_h264_intra.mp4` | oui | oui (code 0) | non | h264 High 4:2:2 Intra, 1920x1080, 25/1, 4:2:2 10 bits ; 500/500 images, 0 erreur(s) ; anomalies : aucune |
| XDCAM HD422 (MPEG-2 4:2:2, GOP long), MXF | `xdcam_hd422.mxf` | oui | oui (code 0) | non | mpeg2video 4:2:2, 1920x1080, 25/1, 4:2:2 8 bits ; 100/100 images, 0 erreur(s) ; anomalies : aucune |
| H.264 4:2:0 8 bits GOP long, MP4 | `h264_lgop.mp4` | oui | oui (code 0) | non | h264 High, 1280x720, 25/1, 4:2:0 8 bits ; 100/100 images, 0 erreur(s) ; anomalies : aucune |
| HEVC Main 10 GOP long, MP4 | `hevc_lgop.mp4` | oui | oui (code 0) | non | hevc Main 10, 1280x720, 25/1, 4:2:0 10 bits ; 100/100 images, 0 erreur(s) ; anomalies : aucune |
| H.264 plage pleine (yuvj420p, pc), MP4 | `fmt_h264_full.mp4` | oui | oui (code 0) | non | h264 High, 640x360, 25/1, 4:2:0 8 bits ; 50/50 images, 0 erreur(s) ; anomalies : gamut |
| Contenu plein-plage annoncé légal, ProRes | `fmt_full_as_tv.mov` | oui | oui (code 0) | non | prores HQ, 640x360, 25/1, 4:2:2 10 bits ; 50/50 images, 0 erreur(s) ; anomalies : black_crush, gamut, range_content_mismatch, white_clip |
| Entrelacé 50i (flashs trame par trame), ProRes | `interlaced_flash.mov` | oui | oui (code 0) | non | prores HQ, 1920x1080, 25/1, 4:2:2 10 bits ; 100/100 images, 0 erreur(s) ; anomalies : pse |
| PsF (progressif marqué entrelacé), ProRes | `psf_prores.mov` | oui | oui (code 0) | non | prores HQ, 1920x1080, 25/1, 4:2:2 10 bits ; 100/100 images, 0 erreur(s) ; anomalies : aucune |
| 23,976p | `rate_23976.mov` | oui | oui (code 0) | non | prores HQ, 1920x1080, 24000/1001, 4:2:2 10 bits ; 480/480 images, 0 erreur(s) ; anomalies : aucune |
| 24p | `rate24_prores.mov` | oui | oui (code 0) | non | prores HQ, 1920x1080, 24/1, 4:2:2 10 bits ; 48/48 images, 0 erreur(s) ; anomalies : aucune |
| 29,97p drop frame | `rate_2997df.mov` | oui | oui (code 0) | non | prores HQ, 1920x1080, 30000/1001, 4:2:2 10 bits ; 600/600 images, 0 erreur(s) ; anomalies : aucune |
| 50p | `rate_50p.mov` | oui | oui (code 0) | non | prores HQ, 1920x1080, 50/1, 4:2:2 10 bits ; 1000/1000 images, 0 erreur(s) ; anomalies : aucune |
| 59,94p drop frame, MXF | `rate_5994df.mxf` | oui | oui (code 0) | non | dnxhd DNXHR HQX, 1920x1080, 60000/1001, 4:2:2 10 bits ; 1199/1199 images, 0 erreur(s) ; anomalies : aucune |
| UHD 3840x2160 2,39 | `fmt_uhd_239.mov` | oui | oui (code 0) | non | prores HQ, 3840x2160, 25/1, 4:2:2 10 bits ; 10/10 images, 0 erreur(s) ; anomalies : gamut |
| 4K DCI 4096x2160 24p | `fmt_dci4k.mov` | oui | oui (code 0) | non | prores HQ, 4096x2160, 24/1, 4:2:2 10 bits ; 11/11 images, 0 erreur(s) ; anomalies : gamut |
| SD PAL 16:9 anamorphique, BT.601 | `sd_pal_169.mov` | oui | oui (code 0) | non | prores HQ, 720x576, 25/1, 4:2:2 10 bits ; 50/50 images, 0 erreur(s) ; anomalies : format, gamut |
| DV PAL 4:2:0 | `sd_dv.mov` | oui | oui (code 0) | non | dvvideo , 720x576, 25/1, 4:2:0 8 bits ; 50/50 images, 0 erreur(s) ; anomalies : format, gamut |
| HDR PQ BT.2020 | `refuse_hdr_pq.mov` | oui | non | HDR ou BT.2020 (transfert smpte2084, primaires bt2020, matrice bt2020nc) : mesures prévues en Phase 7 (BT.2100), pas encore prises en charge. | |
| DV NTSC 4:1:1 | `refuse_dv_ntsc.mov` | oui | non | format de pixel yuv411p : PAD Guard ne sait mesurer que Y'CbCr 4:2:0, 4:2:2 ou 4:4:4, ou RVB, en 8, 10 ou 12 bits. | |
| Cadence variable, MP4 | `refuse_vfr.mp4` | oui | non | cadence variable (25/1 / 250/11) : les images ne sont pas régulièrement espacées, PAD Guard ne la mesure pas. | |
| 48 i/s | `refuse_48p.mov` | oui | non | cadence 48/1 (48 i/s) : PAD Guard ne sait mesurer que 24000/1001 (23,976 i/s) ou 24/1 (24 i/s) ou 25/1 (25 i/s) ou 30000/1001 (29,97 i/s) ou 30/1 (30 i/s) ou 50/1 (50 i/s) ou 60000/1001 (59,94 i/s) ou 60/1 (60 i/s). | |

Le DNxHR HQ d'ASTERIX n'est pas une anomalie de codec avec le profil Arte : « DNX HR/HQ » figure dans la liste du §3.2.2.2, marqué A VERIFIER (« 10bit » contradictoire, question à poser à Arte).
