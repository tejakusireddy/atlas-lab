import pytest
from atlas_science.decisions import decide
from atlas_science.records import Candidate, Molecule


def pool() -> list[Candidate]:
    return [
        Candidate(
            candidate_id=f"c{i:02}",
            reaction_key=f"r{i}",
            group_id="test",
            source_record_id=str(i),
            source_file_sha256="synthetic_test",
            molecules=tuple(
                Molecule.model_validate(
                    dict(role=role, original_smiles=smiles, canonical_smiles=smiles)
                )
                for role, smiles in [
                    ("aryl", "C" * (i + 1)),
                    ("amine", "N"),
                    ("base", "O"),
                    ("ligand", "P"),
                    ("additive", ""),
                ]
            ),
        )
        for i in range(16)
    ]


@pytest.mark.parametrize("policy", ["random", "greedy", "diversity", "ensemble_ucb"])
def test_shared_initial_design_and_budget(policy: str) -> None:
    from typing import cast

    from atlas_science.decisions import Policy

    first, _ = decide(pool(), [], {}, cast(Policy, policy), "random_forest", 42, 8)
    reference, _ = decide(pool(), [], {}, "random", "random_forest", 42, 8)
    assert first["selected_ids"] == reference["selected_ids"]
    selected = first["selected_ids"]
    next_decision, _ = decide(
        pool(),
        selected,
        dict.fromkeys(selected, 50.0),
        cast(Policy, policy),
        "random_forest",
        50,
        8,
    )
    assert len(set(selected + next_decision["selected_ids"])) == 16


@pytest.mark.parametrize("predictor", ["random_forest", "catboost"])
def test_model_decisions_reproduce_and_reject_hidden_labels(predictor: str) -> None:
    from typing import cast

    from atlas_science.decisions import Predictor

    selected = [c.candidate_id for c in pool()[:8]]
    labels = {cid: float(index * 10) for index, cid in enumerate(selected)}
    left, blob = decide(pool(), selected, labels, "ensemble_ucb", cast(Predictor, predictor), 42, 8)
    right, _ = decide(pool(), selected, labels, "ensemble_ucb", cast(Predictor, predictor), 42, 8)
    assert blob and left["model_hash"]
    assert left["scores"] == right["scores"]
    assert left["selected_ids"] == right["selected_ids"]
    with pytest.raises(ValueError, match="released"):
        decide(pool(), selected, labels | {"c15": 100}, "greedy", "random_forest", 42, 8)
