#!/usr/bin/env bash
# Generate the synthetic video fixtures used by the test suite (docs/ROADMAP.md, Phase 0).
#
#   bash tests/fixtures/make_fixtures.sh [--force]
#
# Needs FFmpeg 6+ in the PATH. Existing files are kept unless --force is given.
# All sources are deterministic (fixed noise seeds, no random filters).
#
# Fixtures (1920x1080, 25p, 4:2:2 10-bit, BT.709 tags, legal range, PCM 24-bit 48 kHz):
#   ok_prores.mov      5 s EBU bars + 1 kHz -18 dBFS, 5 s black/silence, 10 s testsrc2 + stereo -23 LUFS.
#                      TC 09:59:50:00 (program at 10:00:00:00 = frame 250). One stereo audio stream.
#   ok_dnxhr.mxf       same content, DNxHR HQX in MXF OP1a.
#   bad_levels.mov     ok_prores + frames 300-324 at Y=975 (104 %) and frames 375-399 at Y=40 (-2.7 %).
#   bad_audio.mov      ok_prores with program audio at -16 LUFS and a 10 ms burst at -0.5 dBTP (t = 15 s).
#   bad_structure.mov  no bars: 10 s black/silence + 10 s program, TC 00:00:00:00.
#   wrong_codec.mov    ok_prores content in ProRes 422 LT.
#   arte_ok.mov        20 s program only (no leaders), TC 10:00:00:00, 3 stereo pairs VO/VF/VI at
#                      -23 LUFS stored as 6 mono tracks, true peak around -12 dBTP.
#   arte_4tracks.mov   arte_ok with VO and VF only (4 mono tracks, no VI).
#   arte_bad.mov       5 s EBU bars + 1 kHz tone, then the arte_ok program (25 s), TC 10:00:00:00;
#                      pair 2 (tracks 3-4) silent for the whole file; 10 ms burst at -0.5 dBTP on
#                      pair 1 at t = 15 s.
#   interlaced_prores.mov  ok_prores made interlaced: the same segments rendered at 50p, then
#                      FFmpeg tinterlace (two successive images -> the two fields of one frame),
#                      25 frames/s, flagged interlaced. Moving pictures show combing.
#   rate24_prores.mov  2 s of testsrc2 at 24 frames/s (FFmpeg -r 24), TC 10:00:00:00, no audio.
#   tc_*.mov / tc_*.mxf  2 s of testsrc2 at 320x180, no audio, to read how the timecode counts:
#                      tc_50p.mov / tc_50p.mxf (50p, TC 10:00:00:30, base 50), tc_5994df.mov (59.94p,
#                      10:00:59;58 drop frame), tc_2997df.mxf (29.97p, 10:00:59;28 drop frame),
#                      tc_23976.mov (23.976p, 10:00:00:23, base 24).
#   rate_50p.mov, rate_2997df.mov, rate_23976.mov, rate_5994df.mxf  the arte_ok program (20 s, VO pair as
#                      2 mono tracks) at 50p, 29.97p (TC 10:00:00;00 drop frame), 23.976p and 59.94p
#                      (DNxHR HQX, TC 10:00:00;00 drop frame).
#   fmt_opatom.mxf     2 s of testsrc2 at 320x180 25p, DNxHR HQX in MXF OP-Atom (video only), TC 10:00:00:00.
#   fmt_h264_intra.mp4 the arte_ok program (20 s, VO as 2 mono tracks) in H.264 High 4:2:2 Intra 10-bit
#                      (libx264, every frame a key frame, like XAVC Intra / AVC-Intra), MP4.
#   fmt_dnxhr_hq_2k.mov  4 s of testsrc2, DNxHR HQ 8 bits 2048x1556 23.976p, TC 00:00:00:00, stereo (like a 2K scan).
#   fmt_prores4444_alpha.mov  2 s of testsrc2 640x360 25p, ProRes 4444 with alpha, no audio.
#   blank_exact.mov, blank_1.mov, blank_3.mov  0.4 s of testsrc2 1920x1036 (1.85) in a 1920x1080 frame,
#                      ProRes HQ 25p, TC 10:00:00:00, no audio: picture from row 22 (centred, Arte 1.85 lines
#                      32-1112), 23 (1 line low) and 25 (3 lines low). Padded in 4:2:2 (in 4:2:0 FFmpeg rounds
#                      the offset to an even row).
#   night_185.mov      1 s night scene in 1.85 (rows 22-1057), ProRes HQ 25p, TC 10:00:00:00, no audio: testsrc2
#                      dimmed to 1/16 (Y about 90), the two top rows and the bottom row of the picture at Y=65
#                      (dark sky and ground: their mean stays under the black threshold), except frames 3, 9,
#                      15 and 21, full brightness (the real edges).
#   bad_levels_50p.mov  ok_prores at 50p with white at Y=975 on frames 600-649 (1 s, 10:00:02:00-10:00:02:49)
#                      and black at Y=40 on frames 750-774 (0.5 s, 10:00:05:00-10:00:05:24).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="$HERE/_work"
FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1

command -v ffmpeg >/dev/null || { echo "ffmpeg introuvable dans le PATH" >&2; exit 1; }

FF=(ffmpeg -v error -nostdin -y)
SIZE=1920x1080
FPS=25            # rate of the generated sources (make_fixture), 50 for interlaced_prores.mov
FIELD_MODE=prog   # scan flag written by make_fixture: prog | tff
AR=48000

# Audio levels, measured with FFmpeg ebur128 (stereo = same signal on L and R).
TONE_AMP=0.125893    # 1 kHz alignment tone, -18 dBFS sine peak
PINK_AMP=0.1         # anoisesrc pink noise at this amplitude: -31.6 LUFS
PINK_GAIN_M23=8.6    # -> -23.0 LUFS (checked for seeds 1, 11, 12, 13, 21)
PINK_GAIN_M16=15.6   # -> -16.0 LUFS integrated including the burst
BURST_AMP=0.944061   # 1 kHz burst, -0.5 dBFS sample peak (true peak -0.5 dBTP)
BURST_SECONDS=0.01

PRORES_HQ=(-c:v prores_ks -profile:v 3 -vendor apl0)
PRORES_LT=(-c:v prores_ks -profile:v 1 -vendor apl0)
DNXHR_HQX=(-c:v dnxhd -profile:v dnxhr_hqx)

mkdir -p "$WORK"

need() {  # need <file>: true if the fixture must be (re)generated
    [[ $FORCE == 1 || ! -s "$HERE/$1" ]]
}

# --- audio --------------------------------------------------------------------------------

# audio_segment <out.wav> <kind> <seconds> [seed] [burst_at_seconds]
#   kind: tone | silence | pink23 | pink16burst | pink23burst
audio_segment() {
    local out=$1 kind=$2 dur=$3 seed=${4:-1} burst_at=${5:-0}
    local n=$((dur * AR))
    local stereo="pan=stereo|c0=c0|c1=c0"
    local trim="atrim=end_sample=$n"
    local graph
    case $kind in
        tone)    graph="aevalsrc='$TONE_AMP*sin(2*PI*1000*t)':s=$AR:d=$dur,$stereo,$trim" ;;
        silence) graph="anullsrc=r=$AR:cl=stereo:d=$dur,$trim" ;;
        pink23)  graph="anoisesrc=color=pink:seed=$seed:amplitude=$PINK_AMP:r=$AR:d=$dur,volume=${PINK_GAIN_M23}dB,$stereo,$trim" ;;
        pink16burst|pink23burst)
            local gain=$PINK_GAIN_M23
            [[ $kind == pink16burst ]] && gain=$PINK_GAIN_M16
            local b0=$burst_at b1
            b1=$(awk "BEGIN{print $burst_at + $BURST_SECONDS}")
            # The noise is muted around the burst so that the burst alone sets the peak.
            graph="anoisesrc=color=pink:seed=$seed:amplitude=$PINK_AMP:r=$AR:d=$dur,volume=${gain}dB,"
            graph+="volume='1-between(t,$b0-0.1,$b1+0.1)':eval=frame,$stereo,$trim[n];"
            graph+="aevalsrc='$BURST_AMP*sin(2*PI*1000*(t-$b0))*between(t,$b0,$b1)':s=$AR:d=$dur,$stereo,$trim[b];"
            graph+="[n][b]amix=inputs=2:normalize=0" ;;
        *) echo "audio_segment: type inconnu $kind" >&2; exit 1 ;;
    esac
    "${FF[@]}" -filter_complex "$graph" -c:a pcm_f32le "$out"
}

# audio_track <out.wav> <segment>...   segment = kind:seconds[:seed[:burst_at]]
audio_track() {
    local out=$1; shift
    local inputs=() i=0 spec kind dur seed burst
    for spec in "$@"; do
        IFS=: read -r kind dur seed burst <<<"$spec"
        audio_segment "$WORK/seg_$i.wav" "$kind" "$dur" "${seed:-1}" "${burst:-0}"
        inputs+=(-i "$WORK/seg_$i.wav")
        i=$((i + 1))
    done
    "${FF[@]}" "${inputs[@]}" -filter_complex "concat=n=$i:v=0:a=1" -c:a pcm_f32le "$out"
    rm -f "$WORK"/seg_*.wav
}

# --- video --------------------------------------------------------------------------------

# make_fixture <out> <timecode> <video segments> <extra video filters> <split_mono 0|1> <codec args...> -- <audio wav>...
#   video segments: "bars:5 black:5 prog:10"
#   extra filters are applied on the yuv422p10le frames (",lutyuv=..."), or "" for none.
make_fixture() {
    local out=$1 tc=$2 segs=$3 extra=$4 split=$5; shift 5
    local codec=()
    while [[ $1 != -- ]]; do codec+=("$1"); shift; done
    shift
    local wavs=("$@")

    local inputs=() graph="" k=0 seg kind dur src
    for seg in $segs; do
        IFS=: read -r kind dur <<<"$seg"
        case $kind in
            bars)  src="pal75bars=s=$SIZE:r=$FPS:d=$dur" ;;   # EBU 75 % colour bars
            black) src="color=c=black:s=$SIZE:r=$FPS:d=$dur" ;;
            prog)  src="testsrc2=s=$SIZE:r=$FPS:d=$dur" ;;
            *) echo "make_fixture: segment inconnu $kind" >&2; exit 1 ;;
        esac
        inputs+=(-f lavfi -i "$src")
        graph+="[$k:v]"
        k=$((k + 1))
    done
    graph+="concat=n=$k:v=1:a=0,scale=out_color_matrix=bt709:out_range=tv,format=yuv422p10le$extra,"
    graph+="setparams=field_mode=$FIELD_MODE:range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709[v]"

    local maps=(-map "[v]") w a=0
    for w in "${wavs[@]}"; do
        inputs+=(-i "$w")
        if [[ $split == 1 ]]; then
            graph+=";[$k:a]channelsplit=channel_layout=stereo[a${a}l][a${a}r]"
            maps+=(-map "[a${a}l]" -map "[a${a}r]")
        else
            maps+=(-map "$k:a")
        fi
        k=$((k + 1)); a=$((a + 1))
    done

    "${FF[@]}" "${inputs[@]}" -filter_complex "$graph" "${maps[@]}" \
        "${codec[@]}" -c:a pcm_s24le -ar $AR -timecode "$tc" "$HERE/$out"
    echo "  $out"
}

echo "Génération des fixtures dans $HERE"

# Classic structure: bars + tone (5 s), black + silence (5 s), program (10 s).
CLASSIC="bars:5 black:5 prog:10"
if need ok_prores.mov || need ok_dnxhr.mxf || need wrong_codec.mov || need bad_levels.mov; then
    audio_track "$WORK/classic_m23.wav" tone:5 silence:5 pink23:10:1
fi
need ok_prores.mov && make_fixture ok_prores.mov 09:59:50:00 "$CLASSIC" "" 0 "${PRORES_HQ[@]}" -- "$WORK/classic_m23.wav"
need ok_dnxhr.mxf && make_fixture ok_dnxhr.mxf 09:59:50:00 "$CLASSIC" "" 0 "${DNXHR_HQX[@]}" -- "$WORK/classic_m23.wav"
need wrong_codec.mov && make_fixture wrong_codec.mov 09:59:50:00 "$CLASSIC" "" 0 "${PRORES_LT[@]}" -- "$WORK/classic_m23.wav"

# White at Y=975 (104 %: above the 103 % luma tolerance, R=G=B stay inside 105 %) on frames
# 300-324 (10:00:02:00-10:00:02:24), black at Y=40 (-2.7 %) on frames 375-399 (10:00:05:00-10:00:05:24).
LEVELS=",lutyuv=y=975:u=512:v=512:enable='between(n,300,324)',lutyuv=y=40:u=512:v=512:enable='between(n,375,399)'"
need bad_levels.mov && make_fixture bad_levels.mov 09:59:50:00 "$CLASSIC" "$LEVELS" 0 "${PRORES_HQ[@]}" -- "$WORK/classic_m23.wav"

if need bad_audio.mov; then
    audio_track "$WORK/classic_m16.wav" tone:5 silence:5 pink16burst:10:1:5
    make_fixture bad_audio.mov 09:59:50:00 "$CLASSIC" "" 0 "${PRORES_HQ[@]}" -- "$WORK/classic_m16.wav"
fi

if need bad_structure.mov; then
    audio_track "$WORK/nobars_m23.wav" silence:10 pink23:10:1
    make_fixture bad_structure.mov 00:00:00:00 "black:10 prog:10" "" 0 "${PRORES_HQ[@]}" -- "$WORK/nobars_m23.wav"
fi

# Arte: no leaders, the first frame is the first program frame. VO / VF / VI as 6 mono tracks.
if need arte_ok.mov || need arte_4tracks.mov; then
    audio_track "$WORK/arte_vo.wav" pink23:20:11
    audio_track "$WORK/arte_vf.wav" pink23:20:12
    audio_track "$WORK/arte_vi.wav" pink23:20:13
fi
need arte_ok.mov && make_fixture arte_ok.mov 10:00:00:00 "prog:20" "" 1 "${PRORES_HQ[@]}" -- \
    "$WORK/arte_vo.wav" "$WORK/arte_vf.wav" "$WORK/arte_vi.wav"
# Same program with VO and VF only (4 mono tracks), like an Arte master without a VI.
need arte_4tracks.mov && make_fixture arte_4tracks.mov 10:00:00:00 "prog:20" "" 1 "${PRORES_HQ[@]}" -- \
    "$WORK/arte_vo.wav" "$WORK/arte_vf.wav"
if need arte_bad.mov; then
    audio_track "$WORK/arte_bad_vo.wav" tone:5 pink23burst:20:11:10
    audio_track "$WORK/arte_bad_vf.wav" silence:25
    audio_track "$WORK/arte_bad_vi.wav" tone:5 pink23:20:13
    make_fixture arte_bad.mov 10:00:00:00 "bars:5 prog:20" "" 1 "${PRORES_HQ[@]}" -- \
        "$WORK/arte_bad_vo.wav" "$WORK/arte_bad_vf.wav" "$WORK/arte_bad_vi.wav"
fi

# Interlaced variant of ok_prores: sources at 50p, two successive images become the top and
# bottom fields of one 25 frames/s frame.
if need interlaced_prores.mov; then
    [[ -s "$WORK/classic_m23.wav" ]] || audio_track "$WORK/classic_m23.wav" tone:5 silence:5 pink23:10:1
    FPS=50 FIELD_MODE=tff make_fixture interlaced_prores.mov 09:59:50:00 "$CLASSIC" ",tinterlace=mode=interleave_top" 0 \
        "${PRORES_HQ[@]}" -flags +ilme+ildct -- "$WORK/classic_m23.wav"
fi

if need rate24_prores.mov; then
    "${FF[@]}" -f lavfi -i "testsrc2=s=$SIZE:r=24:d=2" \
        -vf "scale=out_color_matrix=bt709:out_range=tv,format=yuv422p10le,setparams=field_mode=prog:range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709" \
        -r 24 "${PRORES_HQ[@]}" -timecode 10:00:00:00 "$HERE/rate24_prores.mov"
    echo "  rate24_prores.mov"
fi

# Other frame rates: the same programs, the sources generated at that rate.
if need rate_50p.mov || need rate_2997df.mov || need rate_23976.mov || need rate_5994df.mxf; then
    audio_track "$WORK/rate_vo.wav" pink23:20:11
fi
need rate_50p.mov && FPS=50 make_fixture rate_50p.mov 10:00:00:00 "prog:20" "" 1 "${PRORES_HQ[@]}" -- "$WORK/rate_vo.wav"
need rate_2997df.mov && FPS=30000/1001 make_fixture rate_2997df.mov "10:00:00;00" "prog:20" "" 1 "${PRORES_HQ[@]}" -- "$WORK/rate_vo.wav"
need rate_23976.mov && FPS=24000/1001 make_fixture rate_23976.mov 10:00:00:00 "prog:20" "" 1 "${PRORES_HQ[@]}" -- "$WORK/rate_vo.wav"
need rate_5994df.mxf && FPS=60000/1001 make_fixture rate_5994df.mxf "10:00:00;00" "prog:20" "" 1 "${DNXHR_HQX[@]}" -- "$WORK/rate_vo.wav"
LEVELS50=",lutyuv=y=975:u=512:v=512:enable='between(n,600,649)',lutyuv=y=40:u=512:v=512:enable='between(n,750,774)'"
if need bad_levels_50p.mov; then
    [[ -s "$WORK/classic_m23.wav" ]] || audio_track "$WORK/classic_m23.wav" tone:5 silence:5 pink23:10:1
    FPS=50 make_fixture bad_levels_50p.mov 09:59:50:00 "$CLASSIC" "$LEVELS50" 0 "${PRORES_HQ[@]}" -- "$WORK/classic_m23.wav"
fi

# Containers and codecs.
if need fmt_opatom.mxf; then
    "${FF[@]}" -f lavfi -i "testsrc2=s=320x180:r=25:d=2" \
        -vf "format=yuv422p10le,setparams=field_mode=prog:range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709" \
        "${DNXHR_HQX[@]}" -timecode 10:00:00:00 -f mxf_opatom "$HERE/fmt_opatom.mxf"
    echo "  fmt_opatom.mxf"
fi
if need fmt_h264_intra.mp4; then
    [[ -s "$WORK/rate_vo.wav" ]] || audio_track "$WORK/rate_vo.wav" pink23:20:11
    make_fixture fmt_h264_intra.mp4 10:00:00:00 "prog:20" "" 1 -c:v libx264 -profile:v high422 -pix_fmt yuv422p10le \
        -x264-params keyint=1:min-keyint=1 -b:v 10M -- "$WORK/rate_vo.wav"
fi
# A 2K full-aperture scan like the ASTERIX file of the acceptance: DNxHR HQ 8 bits 2048x1556 23.976p.
if need fmt_dnxhr_hq_2k.mov; then
    audio_track "$WORK/scan.wav" pink23:4:11
    SIZE=2048x1556 FPS=24000/1001 make_fixture fmt_dnxhr_hq_2k.mov 00:00:00:00 "prog:4" "" 0 \
        -c:v dnxhd -profile:v dnxhr_hq -pix_fmt yuv422p -- "$WORK/scan.wav"
fi
# ProRes 4444 with an alpha plane (decoded yuva444p12le by FFmpeg).
if need fmt_prores4444_alpha.mov; then
    "${FF[@]}" -f lavfi -i "testsrc2=s=640x360:r=25:d=2" \
        -vf "format=yuva444p10le,setparams=field_mode=prog:range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709" \
        -c:v prores_ks -profile:v 4 -pix_fmt yuva444p10le -timecode 10:00:00:00 "$HERE/fmt_prores4444_alpha.mov"
    echo "  fmt_prores4444_alpha.mov"
fi
# Coding range: full range tagged as such (H.264 yuvj420p, pc), full-range content tagged narrow
# (ProRes cannot carry the range: the levels are full, the tag says tv), and an R'G'B' file.
BOXES="drawbox=x=0:y=0:w=96:h=96:color=white:t=fill,drawbox=x=96:y=0:w=96:h=96:color=black:t=fill"
FULL="$BOXES,scale=out_color_matrix=bt709:out_range=pc"
if need fmt_h264_full.mp4; then
    "${FF[@]}" -f lavfi -i "testsrc2=s=640x360:r=25:d=2" \
        -vf "$FULL,format=yuvj420p,setparams=field_mode=prog:range=pc:color_primaries=bt709:color_trc=bt709:colorspace=bt709" \
        -c:v libx264 -pix_fmt yuvj420p -color_range pc -g 25 -timecode 10:00:00:00 "$HERE/fmt_h264_full.mp4"
    echo "  fmt_h264_full.mp4"
fi
if need fmt_full_as_tv.mov; then
    "${FF[@]}" -f lavfi -i "testsrc2=s=640x360:r=25:d=2" \
        -vf "$FULL,format=yuv422p10le,setparams=field_mode=prog:range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709" \
        "${PRORES_HQ[@]}" -timecode 10:00:00:00 "$HERE/fmt_full_as_tv.mov"
    echo "  fmt_full_as_tv.mov"
fi
if need fmt_dnxhr444_rgb.mov; then
    "${FF[@]}" -f lavfi -i "testsrc2=s=640x360:r=25:d=2" \
        -vf "format=gbrp10le,setparams=field_mode=prog:range=pc:color_primaries=bt709:color_trc=bt709:colorspace=gbr" \
        -c:v dnxhd -profile:v dnxhr_444 -pix_fmt gbrp10le -timecode 10:00:00:00 "$HERE/fmt_dnxhr444_rgb.mov"
    echo "  fmt_dnxhr444_rgb.mov"
fi
# Interlaced flashes: 50p sources, every other image darkened, then two successive images make the
# top and bottom fields of one frame (25 frames/s, tff). Each frame looks the same (bright top field,
# dark bottom field): no change from frame to frame, 50 changes per second from field to field.
if need interlaced_flash.mov; then
    audio_track "$WORK/flash.wav" pink23:4:11
    FPS=50 FIELD_MODE=tff make_fixture interlaced_flash.mov 10:00:00:00 "prog:4" \
        ",lutyuv=y='64+(val-64)/5':u='512+(val-512)/5':v='512+(val-512)/5':enable='mod(n,2)',tinterlace=mode=interleave_top" 1 \
        "${PRORES_HQ[@]}" -flags +ilme+ildct -- "$WORK/flash.wav"
fi
# PsF: progressive pictures flagged interlaced (ProRes coded as fields).
if need psf_prores.mov; then
    [[ -s "$WORK/flash.wav" ]] || audio_track "$WORK/flash.wav" pink23:4:11
    FIELD_MODE=tff make_fixture psf_prores.mov 10:00:00:00 "prog:4" "" 1 "${PRORES_HQ[@]}" -flags +ildct \
        -- "$WORK/flash.wav"
fi
# Long GOP: XDCAM HD422 (MPEG-2 4:2:2 Profile, 50 Mbit/s, GOP 12 with B frames, 1080i50 tff, MXF,
# mono tracks), H.264 4:2:0 8 bits and HEVC 4:2:0 10 bits (GOP 25, MP4).
if need xdcam_hd422.mxf || need h264_lgop.mp4 || need hevc_lgop.mp4; then
    [[ -s "$WORK/flash.wav" ]] || audio_track "$WORK/flash.wav" pink23:4:11
fi
need xdcam_hd422.mxf && FIELD_MODE=tff make_fixture xdcam_hd422.mxf 10:00:00:00 "prog:4" "" 1 \
    -c:v mpeg2video -pix_fmt yuv422p -profile:v 0 -level:v 2 -b:v 50M -maxrate 50M -minrate 50M \
    -bufsize 17825792 -g 12 -bf 2 -flags +ildct+ilme -- "$WORK/flash.wav"
need h264_lgop.mp4 && SIZE=1280x720 make_fixture h264_lgop.mp4 10:00:00:00 "prog:4" "" 0 \
    -c:v libx264 -pix_fmt yuv420p -g 25 -bf 2 -- "$WORK/flash.wav"
need hevc_lgop.mp4 && SIZE=1280x720 make_fixture hevc_lgop.mp4 10:00:00:00 "prog:4" "" 0 \
    -c:v libx265 -pix_fmt yuv420p10le -x265-params log-level=error:keyint=25 -- "$WORK/flash.wav"
# SD: 625 lines, 16:9 anamorphic (pixels 64:45), BT.601 matrix (bt470bg), 25i top field first, ProRes;
# and DV PAL (4:2:0 8 bits, bottom field first).
SD601="scale=720:576:out_color_matrix=bt470bg:out_range=tv,format=yuv422p10le,setsar=64/45"
if need sd_pal_169.mov; then
    "${FF[@]}" -f lavfi -i "testsrc2=s=1024x576:r=25:d=2" \
        -vf "$SD601,setparams=field_mode=tff:range=tv:color_primaries=bt470bg:color_trc=bt709:colorspace=bt470bg" \
        "${PRORES_HQ[@]}" -flags +ildct -timecode 10:00:00:00 "$HERE/sd_pal_169.mov"
    echo "  sd_pal_169.mov"
fi
if need sd_dv.mov; then
    "${FF[@]}" -f lavfi -i "testsrc2=s=720x576:r=25:d=2" \
        -vf "scale=out_color_matrix=bt470bg:out_range=tv,format=yuv420p,setparams=field_mode=bff:range=tv:colorspace=bt470bg" \
        -c:v dvvideo -timecode 10:00:00:00 "$HERE/sd_dv.mov"
    echo "  sd_dv.mov"
fi
# What PAD Guard refuses (it cannot measure them): HDR PQ BT.2020 (Phase 7), DV NTSC 4:1:1,
# a variable frame rate, 48 frames/s.
if need refuse_hdr_pq.mov; then
    "${FF[@]}" -f lavfi -i "testsrc2=s=640x360:r=25:d=1" \
        -vf "format=yuv422p10le,setparams=field_mode=prog:range=tv:color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc" \
        "${PRORES_HQ[@]}" "$HERE/refuse_hdr_pq.mov"
    echo "  refuse_hdr_pq.mov"
fi
if need refuse_dv_ntsc.mov; then
    "${FF[@]}" -f lavfi -i "testsrc2=s=720x480:r=30000/1001:d=1" -vf "format=yuv411p" -c:v dvvideo "$HERE/refuse_dv_ntsc.mov"
    echo "  refuse_dv_ntsc.mov"
fi
if need refuse_vfr.mp4; then
    "${FF[@]}" -f lavfi -i "testsrc2=s=640x360:r=25:d=4" -vf "setpts='PTS+if(gt(N,50),0.4/TB,0)'" -fps_mode vfr \
        -c:v libx264 -pix_fmt yuv420p "$HERE/refuse_vfr.mp4"
    echo "  refuse_vfr.mp4"
fi
if need refuse_48p.mov; then
    "${FF[@]}" -f lavfi -i "testsrc2=s=640x360:r=48:d=1" -vf "format=yuv422p10le" "${PRORES_HQ[@]}" "$HERE/refuse_48p.mov"
    echo "  refuse_48p.mov"
fi
# Blanking: a 1.85 picture at its exact rows, one line low, three lines low.
for shift in exact:22 1:23 3:25; do
    IFS=: read -r name row <<<"$shift"
    if need "blank_$name.mov"; then
        "${FF[@]}" -f lavfi -i "testsrc2=s=1920x1036:r=25:d=0.4" \
            -vf "scale=out_color_matrix=bt709:out_range=tv,format=yuv422p10le,pad=1920:1080:0:$row:black,setparams=field_mode=prog:range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709" \
            "${PRORES_HQ[@]}" -timecode 10:00:00:00 "$HERE/blank_$name.mov"
        echo "  blank_$name.mov"
    fi
done
# Night scene in 1.85: dark sky and ground on the edges of the picture, four bright frames.
if need night_185.mov; then
    NIGHT="[0:v]scale=out_color_matrix=bt709:out_range=tv,format=yuv422p10le,split=3[a][b][c];"
    NIGHT+="[a]lutyuv=y='64+(val-64)/16':u=512:v=512[dim];"
    NIGHT+="[b]crop=1920:2:0:0,lutyuv=y=65:u=512:v=512,split[sky][edge];[edge]crop=1920:1:0:0[ground];"
    NIGHT+="[dim][sky]overlay=0:0:format=yuv422p10[top];[top][ground]overlay=0:1035:format=yuv422p10[night];"
    NIGHT+="[night][c]overlay=0:0:format=yuv422p10:enable='eq(mod(n\,6)\,3)',pad=1920:1080:0:22:black,"
    NIGHT+="setparams=field_mode=prog:range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709[v]"
    "${FF[@]}" -f lavfi -i "testsrc2=s=1920x1036:r=25:d=1" -filter_complex "$NIGHT" -map "[v]" \
        "${PRORES_HQ[@]}" -timecode 10:00:00:00 "$HERE/night_185.mov"
    echo "  night_185.mov"
fi
# Resolutions: UHD letterboxed to 2.39 (3840x1608 active), 4K DCI full frame (4096x2160), 10 frames each.
if need fmt_uhd_239.mov; then
    "${FF[@]}" -f lavfi -i "testsrc2=s=3840x1608:r=25:d=0.4" \
        -vf "pad=3840:2160:0:276:black,format=yuv422p10le,setparams=field_mode=prog:range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709" \
        "${PRORES_HQ[@]}" -timecode 10:00:00:00 "$HERE/fmt_uhd_239.mov"
    echo "  fmt_uhd_239.mov"
fi
if need fmt_dci4k.mov; then
    "${FF[@]}" -f lavfi -i "testsrc2=s=4096x2160:r=24:d=0.42" \
        -vf "format=yuv422p10le,setparams=field_mode=prog:range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709" \
        "${PRORES_HQ[@]}" -timecode 10:00:00:00 "$HERE/fmt_dci4k.mov"
    echo "  fmt_dci4k.mov"
fi

# Timecode fixtures: FFmpeg writes the base (tmcd number of frames, MXF rounded timecode base)
# and the drop frame flag from the rate and the separator of -timecode.
tc_fixture() {  # tc_fixture <out> <rate> <timecode> <codec args...>
    local out=$1 rate=$2 tc=$3; shift 3
    "${FF[@]}" -f lavfi -i "testsrc2=s=320x180:r=$rate:d=2"         -vf "format=yuv422p10le,setparams=field_mode=prog:range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709"         "$@" -timecode "$tc" "$HERE/$out"
    echo "  $out"
}
need tc_50p.mov && tc_fixture tc_50p.mov 50 10:00:00:30 "${PRORES_HQ[@]}"
need tc_50p.mxf && tc_fixture tc_50p.mxf 50 10:00:00:30 "${DNXHR_HQX[@]}"
need tc_5994df.mov && tc_fixture tc_5994df.mov 60000/1001 "10:00:59;58" "${PRORES_HQ[@]}"
need tc_2997df.mxf && tc_fixture tc_2997df.mxf 30000/1001 "10:00:59;28" "${DNXHR_HQX[@]}"
need tc_23976.mov && tc_fixture tc_23976.mov 24000/1001 10:00:00:23 "${PRORES_HQ[@]}"

rm -rf "$WORK"
echo "Terminé."
