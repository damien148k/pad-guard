"""releve-norme: a norm surveyed by hand, every row checked in its PDF by the code, and its review table
(decision of Damien, 28 October 2026). The PDF is generated (pdf_fixture), the norms are those of the repository."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

import pdf_fixture
from pad_guard.draft import releve
from pad_guard.profiles import resolve_profile
from pad_guard.profiles.resolve import capped_norm_values, load_norm

from conftest import ROOT, TEST_PROFILES
from test_draft import R128_QUOTE, TP_QUOTE


@pytest.fixture(scope="module")
def doc_pdf(tmp_path_factory) -> Path:
    return pdf_fixture.make(tmp_path_factory.mktemp("pdf") / "cst_rt099.pdf")


@pytest.fixture
def lab(tmp_path, doc_pdf) -> Path:
    """tmp/ as the repository: normes/ (without sources), the PDF in normes/sources/, docs/normes/."""
    shutil.copytree(ROOT / "normes", tmp_path / "normes", ignore=shutil.ignore_patterns("sources", "drafts"))
    (tmp_path / "normes" / "sources").mkdir()
    shutil.copy(doc_pdf, tmp_path / "normes" / "sources" / "cst_rt099.pdf")
    (tmp_path / "normes" / "releves").mkdir(exist_ok=True)
    return tmp_path


def _survey(lab: Path, rows: list[dict], **extra) -> Path:
    data = {
        "meta": {"name": "cst_rt099", "document": {"title": "CST-RT-099 — Recommandation de test", "version": "V1"},
                 "source_pdf": "normes/sources/cst_rt099.pdf", "extends": ["ebu_r128"],
                 "refers_to": [{"norm": "ebu_r128", "source": f"CST-RT-099 V1 p. 1 : « {R128_QUOTE} »"}],
                 "applies": "on_reference"},
        "libelle": "CST-RT-099 V1", "releve_par": "test", "releve_le": "2026-10-28", "valeurs": rows, **extra}
    path = lab / "normes" / "releves" / "cst_rt099.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


ROWS = [
    {"champ": "audio.true_peak_max_dbtp", "valeur": -1.0, "page": 1, "citation": TP_QUOTE, "remarque": "Phrase | entière."},
    {"champ": "audio.sample_rate", "valeur": 48000, "page": 2, "citation": "Audio | 48 kHz, 24 bits"},
]


def test_survey_writes_the_norm_and_its_table(lab) -> None:
    path = _survey(lab, ROWS, non_retenus=[{"sujet": "structure.timecode.program_start", "page": 2,
                                            "citation": "Le timecode de la première image du programme est 10:00:00:00",
                                            "remarque": "Exemple de ligne sans valeur."}])
    written, table = releve.run(path, lab / "normes", lab / "docs" / "normes", root=lab)
    norm = load_norm(written)
    assert norm.meta.source_pdf_sha256 and norm.meta.extends == ["ebu_r128"]
    raw = yaml.safe_load(written.read_text(encoding="utf-8"))
    assert list(raw["meta"])[:2] == ["kind", "name"]
    assert raw["audio"] == {"true_peak_max_dbtp": -1.0, "sample_rate": 48000}
    assert raw["sources"]["audio.sample_rate"] == "CST-RT-099 V1 p. 2 : « Audio | 48 kHz, 24 bits »"
    md = table.read_text(encoding="utf-8")
    assert "| `audio.sample_rate`" in md and "| `48000` | 2 | « Audio \\| 48 kHz, 24 bits » |" in md
    assert "Phrase \\| entière." in md  # a pipe in a cell does not break the table
    assert "## Lu dans la norme, sans valeur dans PAD Guard" in md and "Relu et validé par" in md
    assert "`ebu_r128`" in md  # the reference, shown, its values not copied


@pytest.mark.parametrize("row, reason", [
    ({"champ": "audio.true_peak_max_dbtp", "valeur": -2.0, "page": 1, "citation": TP_QUOTE}, "nombre -2"),
    ({"champ": "audio.true_peak_max_dbtp", "valeur": -1.0, "page": 2, "citation": TP_QUOTE}, "trouvée p. 1"),
    ({"champ": "format.containers", "valeur": ["mxf"], "page": 1, "citation": TP_QUOTE}, "paramètre interne"),
    ({"champ": "audio.true_peak_max_dbtp", "valeur": -1.0, "page": 1, "citation": TP_QUOTE, "controle": "citation"},
     "toujours en entier"),
])
def test_one_refused_row_writes_nothing(lab, row, reason) -> None:
    path = _survey(lab, [ROWS[1], row])
    with pytest.raises(releve.ReleveError, match=reason):
        releve.run(path, lab / "normes", lab / "docs" / "normes", root=lab)
    assert not (lab / "normes" / "cst_rt099.yaml").exists() and not (lab / "docs" / "normes").exists()


def test_verify_mode_keeps_the_norm_file(lab) -> None:
    norm = lab / "normes" / "cst_rt099.yaml"
    releve.run(_survey(lab, ROWS), lab / "normes", lab / "docs" / "normes", root=lab)
    text = norm.read_text(encoding="utf-8")
    path = _survey(lab, ROWS, fichier_norme="verifier")
    assert releve.run(path, lab / "normes", lab / "docs" / "normes", root=lab)[0] is None
    assert norm.read_text(encoding="utf-8") == text
    path = _survey(lab, ROWS[:1], fichier_norme="verifier")
    with pytest.raises(releve.ReleveError, match="audio.sample_rate : dans cst_rt099.yaml"):
        releve.run(path, lab / "normes", lab / "docs" / "normes", root=lab)


def test_norm_without_values_gets_its_table_only(lab) -> None:
    unused = [{"sujet": "Méthode", "page": 1, "citation": TP_QUOTE, "remarque": "Aucun seuil."}]
    path = _survey(lab, [], fichier_norme="aucun", non_retenus=unused)
    written, table = releve.run(path, lab / "normes", lab / "docs" / "normes", root=lab)
    assert written is None and not (lab / "normes" / "cst_rt099.yaml").exists()
    assert "pas de fichier dans `normes/`" in table.read_text(encoding="utf-8")
    with pytest.raises(releve.ReleveError, match="choisir « ecrire »"):
        releve.run(_survey(lab, ROWS, fichier_norme="aucun"), lab / "normes", lab / "docs" / "normes", root=lab)


def test_rt040_short_programmes_through_r128_s1(lab) -> None:
    """A client referring to CST-RT-040: short programmes at -23 LUFS (RT 040), ± 0.2 LU (R 128 s1, by the
    transitive reference), short term ≤ -20 LUFS (RT 040 wins over s1's -18); 2 minutes; long at -23 ± 1."""
    raw = yaml.safe_load((TEST_PROFILES / "test_classic.yaml").read_text(encoding="utf-8"))
    client = "Annexe test p. 2 : « Recommandation Technique PAD fichier Diffuseurs »"
    raw["meta"]["extends"] = ["ebu_r103", "ebu_r128", "cst_rt040", "lumiris_maison"]
    raw["meta"]["refers_to"] = [{"norm": "cst_rt040", "source": client}]
    raw["audio"].pop("loudness")
    raw["sources"] = {k: v for k, v in (raw.get("sources") or {}).items() if not k.startswith("audio.loudness")}
    path = lab / "client.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True, sort_keys=False), encoding="utf-8")
    r = resolve_profile(path)
    loud = r.profile.audio.loudness
    assert loud.long_program_min_seconds == 120
    assert (loud.short.integrated_lufs, loud.short.integrated_tolerance_lu, loud.short.short_term_max_lufs) == (-23, 0.2, -20)
    assert (loud.long.integrated_lufs, loud.long.integrated_tolerance_lu, loud.long.short_term_dialogue_excursion_lu) == (-23, 1, 7)
    o = r.origins
    assert o["audio.loudness.short.integrated_tolerance_lu"].file == "normes/ebu_r128_s1.yaml"
    assert o["audio.loudness.short.short_term_max_lufs"].file == "normes/cst_rt040.yaml"
    assert not {p for p in capped_norm_values(r) if p.startswith("audio.loudness.")}  # client's requirements


def test_repository_surveys_match_their_norms() -> None:
    """Every survey of normes/releves/ gives the values of its norm (the PDFs are not in the repository:
    the quotes are checked by pad-guard releve-norme, here only the files are compared)."""
    for path in sorted((ROOT / "normes" / "releves").glob("*.yaml")):
        survey = releve.load(path)
        if survey.fichier_norme == "aucun":
            assert not (ROOT / "normes" / f"{path.stem}.yaml").exists()
            continue
        rows = [releve.Checked(r, "") for r in survey.valeurs]
        releve.compare_with_norm(survey, rows, ROOT / "normes" / f"{path.stem}.yaml")
