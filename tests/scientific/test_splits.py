import pytest
from atlas_science.importer import normalize_row
from atlas_science.records import Candidate
from atlas_science.splits import assert_disjoint, create_split


def candidates() -> list[Candidate]:
    result = []
    for index, aryl in enumerate(["Clc1ccccc1", "Brc1ccccc1", "Ic1ccccc1", "Fc1ccccc1"]):
        row = {
            "plate": "synthetic",
            "row": "1",
            "col": str(index),
            "aryl_halide_smiles": aryl,
            "base_smiles": "N",
            "ligand_smiles": "P",
            "additive_smiles": "",
            "yield": "1",
        }
        candidate, _ = normalize_row(row, "synthetic-test")
        result.append(candidate)
    return result


def test_split_is_reproducible_independent_of_row_order() -> None:
    records = candidates()
    assert create_split(records) == create_split(list(reversed(records)))
    split = create_split(records)
    assert (
        len(set(split.train_ids + split.calibration_ids + split.campaign_ids + split.ood_test_ids))
        == 4
    )


def test_same_reaction_with_new_id_is_still_leakage() -> None:
    candidate = candidates()[0]
    duplicate = candidate.model_copy(update={"candidate_id": "different-source-id"})
    with pytest.raises(ValueError, match="leakage"):
        assert_disjoint([[candidate], [duplicate]])


def test_shared_fixed_amine_cannot_be_called_strict_ood() -> None:
    records = candidates()
    assert_disjoint([[records[0]], [records[1]]])
    with pytest.raises(ValueError, match="strict OOD"):
        assert_disjoint([[records[0]], [records[1]]], strict_substrates=True)
