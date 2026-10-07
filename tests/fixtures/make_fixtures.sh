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
#   arte_bad.mov       5 s EBU bars + 1 kHz tone, then the arte_ok program (25 s), TC 10:00:00:00;
#                      pair 2 (tracks 3-4) silent for the whole file; 10 ms burst at -0.5 dBTP on
#                      pair 1 at t = 15 s.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="$HERE/_work"
FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1

command -v ffmpeg >/dev/null || { echo "ffmpeg introuvable dans le PATH" >&2; exit 1; }

FF=(ffmpeg -v error -nostdin -y)
SIZE=1920x1080
FPS=25
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
    graph+="setparams=field_mode=prog:range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709[v]"

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
if need arte_ok.mov; then
    audio_track "$WORK/arte_vo.wav" pink23:20:11
    audio_track "$WORK/arte_vf.wav" pink23:20:12
    audio_track "$WORK/arte_vi.wav" pink23:20:13
    make_fixture arte_ok.mov 10:00:00:00 "prog:20" "" 1 "${PRORES_HQ[@]}" -- \
        "$WORK/arte_vo.wav" "$WORK/arte_vf.wav" "$WORK/arte_vi.wav"
fi
if need arte_bad.mov; then
    audio_track "$WORK/arte_bad_vo.wav" tone:5 pink23burst:20:11:10
    audio_track "$WORK/arte_bad_vf.wav" silence:25
    audio_track "$WORK/arte_bad_vi.wav" tone:5 pink23:20:13
    make_fixture arte_bad.mov 10:00:00:00 "bars:5 prog:20" "" 1 "${PRORES_HQ[@]}" -- \
        "$WORK/arte_bad_vo.wav" "$WORK/arte_bad_vf.wav" "$WORK/arte_bad_vi.wav"
fi

rm -rf "$WORK"
echo "Terminé."
