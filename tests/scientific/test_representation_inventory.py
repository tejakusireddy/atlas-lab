import hashlib
import json
from pathlib import Path

import pytest
from atlas_science.records import Candidate, Molecule
from atlas_science.representation_inventory import inventory, prepare


def candidates() -> list[Candidate]:
    return [
        Candidate(
            candidate_id=f"c{i}",
            reaction_key=f"r{i}",
            group_id=f"g{i}",
            source_record_id=str(i),
            source_file_sha256="synthetic_test",
            molecules=tuple(
                Molecule.model_validate(
                    dict(role=role, original_smiles=smiles, canonical_smiles=smiles)
                )
                for role, smiles in (
                    ("aryl", "C"),
                    ("amine", "N"),
                    ("base", "O"),
                    ("ligand", "P"),
                    ("additive", ""),
                )
            ),
        )
        for i in range(4)
    ]


def test_inventory_is_outcome_free_and_does_not_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    manifest = b'{"fixture":"synthetic_test"}'
    inputs = "\n".join(c.model_dump_json() for c in candidates()).encode()
    (snapshot / "source_manifest.json").write_bytes(manifest)
    (snapshot / "candidates.jsonl").write_bytes(inputs)
    contract = tmp_path / "contract.json"
    contract.write_text(
        json.dumps(
            {
                "source_manifest_sha256": hashlib.sha256(manifest).hexdigest(),
                "candidate_artifact_sha256": hashlib.sha256(inputs).hexdigest(),
            }
        )
    )
    original = Path.read_bytes
    opened: list[str] = []

    def guarded(path: Path) -> bytes:
        assert path.name in {"source_manifest.json", "candidates.jsonl"}
        opened.append(path.name)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded)
    output = tmp_path / "inventory.json"
    result = prepare(snapshot, output, contract)
    assert opened == ["source_manifest.json", "candidates.jsonl"]
    assert result["evaluation_status"] == "not_run"
    assert result["unique_nonempty_molecule_count"] == 4
    assert result["absent_role_counts"]["additive"] == 4
    assert all(row["embedding_status"] == "not_run" for row in result["molecules"])
    with pytest.raises(FileExistsError):
        prepare(snapshot, output, contract)
    (snapshot / "candidates.jsonl").write_bytes(inputs + b"\n")
    with pytest.raises(ValueError, match="contract"):
        prepare(snapshot, tmp_path / "other.json", contract)


def test_inventory_rejects_invalid_roles_and_duplicate_candidates() -> None:
    pool = candidates()
    with pytest.raises(ValueError, match="unique"):
        inventory(pool + pool[:1])
    bad = pool[0].model_copy(update={"molecules": pool[0].molecules[:-1]})
    with pytest.raises(ValueError, match="role"):
        inventory([bad, *pool[1:]])


def test_evaluation_contract_preserves_reference_and_pairing() -> None:
    contract = json.loads(Path("contracts/molmim_evaluation.v1.json").read_text())
    reference = json.loads(Path(contract["scientific_reference"]).read_text())
    for field in ("source_manifest_sha256", "candidate_artifact_sha256", "split_seed"):
        assert contract[field] == reference[field]
    assert contract["status"] == "not_run"
    assert contract["sequential"]["budget"] == reference["budget"] == 48
    assert contract["sequential"]["batch_size"] == reference["batch_size"] == 8
    assert contract["sequential"]["checkpoints"] == [8, 16, 24, 32, 40, 48]
    assert contract["sequential"]["external_training"] is False
    assert contract["prediction"]["tuning_trials_per_arm"] == 0
    assert contract["live_campaign_integration"] is False

    assert (
        hashlib.sha256(
            Path("packages/science/src/atlas_science/baseline.py").read_bytes()
        ).hexdigest()
        == contract["prediction"]["head_source_sha256"]
    )
    assert (
        contract["sequential"]["engine_source_sha256"]
        == reference["scientific_code_sha256"]["packages/science/src/atlas_science/decisions.py"]
    )
