"""Inventory outcome-free molecule inputs before an optional representation evaluation."""

import argparse
import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from atlas_domain.hashing import content_hash
from rdkit import Chem

from atlas_science.features import ROLE_ORDER
from atlas_science.records import Candidate
from atlas_science.splits import create_split


def inventory(candidates: Sequence[Candidate]) -> dict[str, Any]:
    if not candidates or len({c.candidate_id for c in candidates}) != len(candidates):
        raise ValueError("Inventory requires nonempty, unique candidate inputs")
    molecules: dict[str, Counter[str]] = {}
    absent: Counter[str] = Counter()
    for candidate in candidates:
        if len(candidate.molecules) != len(ROLE_ORDER) or {
            m.role for m in candidate.molecules
        } != set(ROLE_ORDER):
            raise ValueError("Candidate must contain exactly one input per molecular role")
        for molecule in candidate.molecules:
            if not molecule.canonical_smiles:
                absent[molecule.role] += 1
            else:
                molecules.setdefault(molecule.canonical_smiles, Counter())[molecule.role] += 1
    rows = []
    for smiles, roles in sorted(molecules.items()):
        mol = Chem.MolFromSmiles(smiles)
        if mol is None or Chem.MolToSmiles(mol) != smiles:
            raise ValueError("Inventory requires valid canonical molecular inputs")
        rows.append(
            {
                "canonical_smiles": smiles,
                "role_counts": dict(sorted(roles.items())),
                "fragment_count": len(Chem.GetMolFrags(mol)),
                "formal_charge": Chem.GetFormalCharge(mol),
                "elements": sorted({atom.GetSymbol() for atom in mol.GetAtoms()}),
                "embedding_status": "not_run",
            }
        )
    split = create_split(candidates, 42)
    group_by_id = {candidate.candidate_id: candidate.group_id for candidate in candidates}
    return {
        "schema_version": "1.0",
        "evaluation_status": "not_run",
        "candidate_count": len(candidates),
        "group_count": len({c.group_id for c in candidates}),
        "unique_nonempty_molecule_count": len(rows),
        "absent_role_counts": {role: absent[role] for role in ROLE_ORDER},
        "split_hash": content_hash(split.model_dump(mode="json")),
        "partitions": {
            name: {
                "candidate_count": len(ids),
                "group_count": len({group_by_id[cid] for cid in ids}),
            }
            for name, ids in (
                ("train", split.train_ids),
                ("calibration", split.calibration_ids),
                ("campaign", split.campaign_ids),
                ("ood_test", split.ood_test_ids),
            )
        },
        "molecules": rows,
    }


def prepare(snapshot: Path, output: Path, contract_path: Path) -> dict[str, Any]:
    """Open only the public manifest and candidate partition; never an outcome loader."""
    contract = json.loads(contract_path.read_text())
    manifest = (snapshot / "source_manifest.json").read_bytes()
    inputs = (snapshot / "candidates.jsonl").read_bytes()
    for value, expected in (
        (manifest, contract["source_manifest_sha256"]),
        (inputs, contract["candidate_artifact_sha256"]),
    ):
        if hashlib.sha256(value).hexdigest() != expected:
            raise ValueError("Input snapshot does not match the evaluation contract")
    candidates = [Candidate.model_validate_json(line) for line in inputs.splitlines()]
    result = inventory(candidates)
    result.update(
        contract_hash=content_hash(contract),
        candidate_artifact_sha256=hashlib.sha256(inputs).hexdigest(),
    )
    with output.open("x") as destination:
        destination.write(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--contract", type=Path, default=Path("contracts/molmim_evaluation.v1.json")
    )
    args = parser.parse_args()
    result = prepare(args.snapshot, args.output, args.contract)
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "evaluation_status",
                    "candidate_count",
                    "unique_nonempty_molecule_count",
                    "absent_role_counts",
                )
            }
        )
    )


if __name__ == "__main__":
    main()
