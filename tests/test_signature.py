"""signer-norme: Vincent signs the review table he read; the signature goes into the norm, refused when the norm
changed since the table, or when a correction is still noted in the table."""

from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from pad_guard.draft import releve, signature
from pad_guard.profiles.resolve import load_norm

from conftest import ROOT
from test_releve import ROWS, _survey, doc_pdf, lab  # noqa: F401  (fixtures)

DAY = dt.date(2026, 10, 31)


@pytest.fixture
def surveyed(lab) -> Path:  # noqa: F811
    path = _survey(lab, ROWS, non_retenus=[{"sujet": "structure.timecode.program_start", "page": 2,
                                            "citation": "Le timecode de la première image du programme est 10:00:00:00",
                                            "remarque": "Exemple."}])
    releve.run(path, lab / "normes", lab / "docs" / "normes", root=lab)
    return lab


def _table(lab: Path) -> Path:
    return lab / "docs" / "normes" / "cst_rt099.md"


def test_table_has_the_reading_box_the_check_column_and_the_stamp(surveyed) -> None:
    md = _table(surveyed).read_text(encoding="utf-8")
    assert md.index("**Comment relire**") < md.index("## Valeurs")
    assert "signer-norme cst_rt099 --par" in md
    assert "| Remarque | OK / correction |" in md and "| Pourquoi aucune valeur | OK / correction |" in md
    assert "| Version citée | OK / correction |" in md
    fp = signature.norm_fingerprint(surveyed / "normes" / "cst_rt099.yaml")
    assert signature.stamp_line("cst_rt099", fp) in md
    assert md.rstrip().endswith("Relu par : ____________________  le : ____________")


def test_sign_writes_the_signature_into_the_norm(surveyed) -> None:
    md = _table(surveyed)
    md.write_text(md.read_text(encoding="utf-8").replace("Exemple. | |", "Exemple. | OK |"), encoding="utf-8")
    fp = signature.table_fingerprint(md.read_text(encoding="utf-8"))
    norm, table = signature.sign("cst_rt099", " Vincent ", surveyed, DAY)
    meta = load_norm(norm).meta
    assert (meta.validated_by, meta.validated_at, meta.validated_table_sha256) == ("Vincent", DAY, fp)
    text = table.read_text(encoding="utf-8")
    assert "Relu par Vincent le 31/10/2026" in text and fp in text
    assert "Relu par : ___" not in text
    st = signature.status("cst_rt099", surveyed)
    assert st.signed and st.by == "Vincent" and st.problems == []
    # Signing twice keeps one signature line and one set of keys.
    signature.sign("cst_rt099", "Vincent", surveyed, DAY)
    assert norm.read_text(encoding="utf-8").count("validated_by:") == 1
    assert table.read_text(encoding="utf-8").count("Relu par") == 1


def test_refused_when_the_norm_changed_since_the_table(surveyed) -> None:
    norm = surveyed / "normes" / "cst_rt099.yaml"
    before = norm.read_text(encoding="utf-8")
    norm.write_text(before.replace("sample_rate: 48000", "sample_rate: 44100"), encoding="utf-8")
    with pytest.raises(signature.SignatureError, match="a changé depuis la génération du tableau"):
        signature.sign("cst_rt099", "Vincent", surveyed, DAY)
    assert "validated_by: null" in norm.read_text(encoding="utf-8")
    # A comment does not change the content.
    norm.write_text("# relu\n" + before, encoding="utf-8")
    signature.sign("cst_rt099", "Vincent", surveyed, DAY)


def test_refused_while_a_correction_is_noted(surveyed) -> None:
    md = _table(surveyed)
    md.write_text(md.read_text(encoding="utf-8").replace("24 bits » |  | |", "24 bits » |  | 44,1 kHz p. 3 |"),
                  encoding="utf-8")
    with pytest.raises(signature.SignatureError, match="releve-norme") as exc:
        signature.sign("cst_rt099", "Vincent", surveyed, DAY)
    assert "44,1 kHz p. 3" in str(exc.value)
    assert not load_norm(surveyed / "normes" / "cst_rt099.yaml").meta.validated_by


def test_status_sees_a_table_changed_after_the_signature(surveyed) -> None:
    signature.sign("cst_rt099", "Vincent", surveyed, DAY)
    md = _table(surveyed)
    md.write_text(md.read_text(encoding="utf-8").replace("Exemple.", "Autre."), encoding="utf-8")
    assert signature.status("cst_rt099", surveyed).problems == ["cst_rt099.md a changé depuis la signature"]


def test_a_new_survey_erases_the_signature(surveyed) -> None:
    signature.sign("cst_rt099", "Vincent", surveyed, DAY)
    releve.run(surveyed / "normes" / "releves" / "cst_rt099.yaml", surveyed / "normes", surveyed / "docs" / "normes",
               root=surveyed)
    meta = load_norm(surveyed / "normes" / "cst_rt099.yaml").meta
    assert meta.validated_by is None and meta.validated_table_sha256 is None
    assert "Relu par : ___" in _table(surveyed).read_text(encoding="utf-8")


def test_verify_mode_erases_the_signature_too(lab) -> None:  # noqa: F811
    path = _survey(lab, ROWS)
    releve.run(path, lab / "normes", lab / "docs" / "normes", root=lab)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["fichier_norme"] = "verifier"
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    signature.sign("cst_rt099", "Vincent", lab, DAY)
    releve.run(path, lab / "normes", lab / "docs" / "normes", root=lab)
    assert load_norm(lab / "normes" / "cst_rt099.yaml").meta.validated_by is None


def test_norm_without_values_has_nothing_to_sign(lab) -> None:  # noqa: F811
    path = _survey(lab, [], fichier_norme="aucun")
    _, table = releve.run(path, lab / "normes", lab / "docs" / "normes", root=lab)
    assert "rien n'est à signer" in table.read_text(encoding="utf-8")
    with pytest.raises(signature.SignatureError, match="rien n'est à signer"):
        signature.sign("cst_rt099", "Vincent", lab, DAY)


def test_house_rules_sign_with_comments_kept(tmp_path) -> None:
    shutil.copytree(ROOT / "normes", tmp_path / "normes", ignore=shutil.ignore_patterns("sources", "drafts"))
    (tmp_path / "docs").mkdir()
    shutil.copy(ROOT / "docs" / "VALEURS_MAISON.md", tmp_path / "docs" / "VALEURS_MAISON.md")
    norm, table = signature.sign(signature.HOUSE, "Vincent", tmp_path, DAY)
    text = norm.read_text(encoding="utf-8")
    assert "# A VERIFIER Vincent" in text and "  validated_by: \"Vincent\"" in text
    assert load_norm(norm).meta.validated_at == DAY
    assert "Relu par Vincent le 31/10/2026" in table.read_text(encoding="utf-8")
    assert signature.status(signature.HOUSE, tmp_path).problems == []


def test_cli_refuses_without_a_matching_table(tmp_path, monkeypatch) -> None:
    from pad_guard.cli import app

    shutil.copytree(ROOT / "normes", tmp_path / "normes", ignore=shutil.ignore_patterns("sources", "drafts"))
    monkeypatch.setattr(releve, "ROOT", tmp_path)
    result = CliRunner().invoke(app, ["signer-norme", "ebu_r128", "--par", "Vincent"])
    assert result.exit_code != 0 and "introuvable" in result.output


def test_repository_tables_match_their_norms() -> None:
    """Every table of the repository carries the fingerprint of its norm as it is now: a norm changed without a new
    table (releve-norme, or VALEURS_MAISON.md by hand) fails here; a signed norm still covers its table."""
    names = [p.stem for p in (ROOT / "normes" / "releves").glob("*.yaml")
             if (ROOT / "normes" / f"{p.stem}.yaml").exists()] + [signature.HOUSE]
    for name in names:
        current = signature.norm_fingerprint(ROOT / "normes" / f"{name}.yaml")
        text = signature.table_path(name, ROOT).read_text(encoding="utf-8")
        assert signature.stamp_line(name, current) in text, f"{name} : empreinte attendue {current}"
        st = signature.status(name, ROOT)
        assert st.problems == [], f"{name} : {st.problems}"
