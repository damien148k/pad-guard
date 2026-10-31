from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
PROFILES = ROOT / "profiles"
TEST_PROFILES = ROOT / "tests" / "profiles"

FIXTURE_FILES = (
    "ok_prores.mov",
    "ok_dnxhr.mxf",
    "bad_levels.mov",
    "bad_audio.mov",
    "bad_structure.mov",
    "wrong_codec.mov",
    "arte_ok.mov",
    "arte_4tracks.mov",
    "arte_bad.mov",
    "interlaced_prores.mov",
    "rate24_prores.mov",
    "tc_50p.mov",
    "tc_50p.mxf",
    "tc_5994df.mov",
    "tc_2997df.mxf",
    "tc_23976.mov",
    "rate_50p.mov",
    "rate_2997df.mov",
    "rate_23976.mov",
    "rate_5994df.mxf",
    "bad_levels_50p.mov",
    "fmt_opatom.mxf",
    "fmt_h264_intra.mp4",
    "fmt_dnxhr_hq_2k.mov",
    "fmt_prores4444_alpha.mov",
    "blank_exact.mov",
    "blank_1.mov",
    "blank_3.mov",
    "night_185.mov",
    "fmt_h264_full.mp4",
    "fmt_full_as_tv.mov",
    "fmt_dnxhr444_rgb.mov",
    "fmt_uhd_239.mov",
    "fmt_dci4k.mov",
    "interlaced_flash.mov",
    "psf_prores.mov",
    "xdcam_hd422.mxf",
    "h264_lgop.mp4",
    "hevc_lgop.mp4",
    "sd_pal_169.mov",
    "sd_dv.mov",
    "refuse_hdr_pq.mov",
    "refuse_dv_ntsc.mov",
    "refuse_vfr.mp4",
    "refuse_48p.mov",
)


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    """Directory holding the generated video fixtures; generates them on first use."""
    if any(not (FIXTURES / name).is_file() for name in FIXTURE_FILES):
        bash = shutil.which("bash")
        if bash is None or shutil.which("ffmpeg") is None:
            pytest.skip("bash et ffmpeg sont nécessaires pour générer les fixtures vidéo")
        subprocess.run([bash, str(FIXTURES / "make_fixtures.sh")], check=True)
    return FIXTURES
