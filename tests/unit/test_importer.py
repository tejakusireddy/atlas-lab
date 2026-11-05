from pathlib import Path

import pytest
from atlas_science.importer import canonical_smiles, normalize_row, verify_file
from atlas_science.records import Candidate
from pydantic import ValidationError


def synthetic_row(yield_value: str = "32.5") -> dict[str, str]:
    return {
        "plate": "test",
        "row": "1",
        "col": "1",
        "aryl_halide_smiles": "Clc1ccccc1",
        "base_smiles": "N",
        "ligand_smiles": "P",
        "additive_smiles": "",
        "yield": yield_value,
    }


def test_normalization_retains_provenance_without_exposing_outcome() -> None:
    candidate, observation = normalize_row(synthetic_row(), "test-hash")
    assert observation.observed_yield_pct == 32.5
    assert observation.source_record_id == candidate.source_record_id
    assert "yield" not in candidate.model_dump_json()
    with pytest.raises(ValidationError):
        Candidate.model_validate({**candidate.model_dump(), "yield": 32.5})


@pytest.mark.parametrize("raw", ["nan", "inf", "-1", "101", "nonsense"])
def test_invalid_yields_are_retained_but_quarantined(raw: str) -> None:
    _, observation = normalize_row(synthetic_row(raw), "test-hash")
    assert observation.raw_yield == raw
    assert observation.qc_state == "QUARANTINED"
    assert observation.observed_yield_pct is None


def test_missing_yield_is_not_zero() -> None:
    _, observation = normalize_row(synthetic_row(""), "test-hash")
    assert observation.qc_state == "UNOBSERVED"
    assert observation.observed_yield_pct is None
    _, zero = normalize_row(synthetic_row("0"), "test-hash")
    assert zero.qc_state == "PASSED"
    assert zero.observed_yield_pct == 0


def test_equivalent_molecules_have_same_identity() -> None:
    assert canonical_smiles("c1ccccc1Cl") == canonical_smiles("Clc1ccccc1")
    with pytest.raises(ValueError):
        canonical_smiles("not-a-molecule")


def test_checksum_failure_blocks_import(tmp_path: Path) -> None:
    path = tmp_path / "data.csv"
    path.write_text("tampered")
    with pytest.raises(ValueError, match="Checksum"):
        verify_file(path, "0" * 64)
