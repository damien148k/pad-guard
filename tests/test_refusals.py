"""What PAD Guard refuses, and only that (Phase 6): it cannot measure these files reliably."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from pad_guard.cli import EXIT_REFUSED, app
from pad_guard.probe import probe_file
from pad_guard.rules.profile import load_profile

from conftest import PROFILES

pytestmark = pytest.mark.fixtures

TECHNICAL = PROFILES / "lumiris_controle_technique.yaml"


@pytest.mark.parametrize(("name", "reason"), [
    ("refuse_hdr_pq.mov", "HDR ou BT.2020 (transfert smpte2084"),
    ("refuse_dv_ntsc.mov", "format de pixel yuv411p : PAD Guard ne sait mesurer que Y'CbCr 4:2:0, 4:2:2 ou 4:4:4"),
    ("refuse_vfr.mp4", "cadence variable"),
    ("refuse_48p.mov", "cadence 48/1 (48 i/s)"),
])
def test_refused(fixtures_dir, tmp_path, name, reason) -> None:
    r = probe_file(fixtures_dir / name, load_profile(TECHNICAL), TECHNICAL, hash_source=False)
    assert not r.accepted and len(r.refusal_reasons) == 1 and r.refusal_reasons[0].startswith(reason)
    result = CliRunner().invoke(app, ["analyze", str(fixtures_dir / name), "--profile", str(TECHNICAL),
                                      "--out", str(tmp_path / "o")])
    assert result.exit_code == EXIT_REFUSED


def test_unsupported_matrix_refused(fixtures_dir, tmp_path) -> None:
    """A matrix tag PAD Guard has no coefficients for (SMPTE 240M): the measurements would be wrong."""
    import subprocess
    path = tmp_path / "m240.mov"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(fixtures_dir / "psf_prores.mov"), "-map", "0:v",
                    "-c", "copy", "-colorspace", "smpte240m", str(path)], check=True)
    r = probe_file(path, load_profile(TECHNICAL), TECHNICAL, hash_source=False)
    assert not r.accepted and r.refusal_reasons == [
        "matrice de couleur smpte240m : PAD Guard ne sait mesurer que bt709, bt470bg ou smpte170m."]
