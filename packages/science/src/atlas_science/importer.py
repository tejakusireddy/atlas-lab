"""Explicit, checksum-verified import of the primary Doyle reaction table."""

import argparse
import csv
import hashlib
import io
import json
import math
import os
import tempfile
import urllib.request
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Literal

from atlas_domain.hashing import content_hash
from pydantic import BaseModel
from rdkit import Chem, rdBase

from atlas_science.records import Candidate, Molecule, Observation

REVISION = "57e15fdb7f7483c6bf3a601df69f6ac9e5af6965"
BASE_URL = f"https://raw.githubusercontent.com/doylelab/rxnpredict/{REVISION}"
DATA_SHA256 = "fe310b50897e97578078558909efc2edaa7b98ad8939b1caad740a718398ed62"
LICENSE_SHA256 = "0bb1b3bc29bf8fa4f5a2063a3d6bbaec6d2e849d86efef855c765382cb0d427d"
NORMALIZATION_VERSION = "doyle-v1"
# Fixed amine verified across every Doyle row in the independent curated table.
AMINE_SMILES = "Cc1ccc(N)cc1"
AMINE_EVIDENCE = {
    "repository": "https://github.com/schwallergroup/bh-hte-ood",
    "revision": "3a44e398d9fed3f08cf396f1153be2960193f581",
    "file": "data/BH_HTE_Curated_Dataset_v20260219.csv",
    "sha256": "247473787c33fb22ee48a4177593188f2a2c6ef140756566fe4610fee89ba333",
    "filter": "Source == Dreher Doyle 2018",
    "column": "Amine SMILES",
}
ROLES: tuple[Literal["aryl", "amine", "base", "ligand", "additive"], ...] = (
    "aryl",
    "amine",
    "base",
    "ligand",
    "additive",
)


def verify_file(path: Path, expected: str) -> bytes:
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"Checksum mismatch: {path}")
    return data


def fetch_verified(directory: Path, name: str, expected: str) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / name
    if destination.exists():
        verify_file(destination, expected)
        return destination
    with urllib.request.urlopen(f"{BASE_URL}/{name}", timeout=60) as response:
        data = response.read(10_000_001)
    if len(data) > 10_000_000 or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"Downloaded file failed size/checksum verification: {name}")
    with tempfile.NamedTemporaryFile(dir=directory, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(data)
    temporary.replace(destination)
    return destination


@lru_cache(maxsize=4096)
def canonical_smiles(smiles: str) -> str:
    molecule = Chem.MolFromSmiles(smiles)
    if molecule is None:
        raise ValueError("Invalid SMILES")
    return str(Chem.MolToSmiles(molecule, canonical=True, isomericSmiles=True))


def normalize_row(row: dict[str, str], file_hash: str) -> tuple[Candidate, Observation]:
    record_id = f"plate:{row['plate']}:row:{row['row']}:col:{row['col']}"
    values = (
        row["aryl_halide_smiles"],
        AMINE_SMILES,
        row["base_smiles"],
        row["ligand_smiles"],
        row["additive_smiles"],
    )
    molecules = []
    for role, value in zip(ROLES, values, strict=True):
        if not value and role != "additive":
            raise ValueError(f"Missing {role} SMILES")
        molecules.append(
            Molecule(
                role=role,
                original_smiles=value,
                canonical_smiles=canonical_smiles(value) if value else "",
            )
        )
    identities = {m.role: m.canonical_smiles for m in molecules}
    reaction_key = content_hash({str(role): smiles for role, smiles in identities.items()})
    group_id = content_hash({"aryl": identities["aryl"], "amine": identities["amine"]})
    candidate = Candidate(
        candidate_id=f"doyle2018:{record_id}",
        reaction_key=reaction_key,
        group_id=group_id,
        source_record_id=record_id,
        source_file_sha256=file_hash,
        molecules=tuple(molecules),
    )
    raw = row["yield"].strip()
    observed_value: float | None = None
    state: Literal["PASSED", "QUARANTINED", "UNOBSERVED"] = "UNOBSERVED"
    reason: str | None = "missing_yield"
    if raw:
        try:
            parsed = float(raw)
            if not math.isfinite(parsed) or not 0 <= parsed <= 100:
                raise ValueError("out_of_range")
            observed_value, state, reason = parsed, "PASSED", None
        except ValueError:
            state, reason = "QUARANTINED", "invalid_yield_pct"
    return candidate, Observation(
        candidate_id=candidate.candidate_id,
        source_record_id=record_id,
        source_file_sha256=file_hash,
        source_kind="historical_observed",
        raw_yield=raw,
        observed_yield_pct=observed_value,
        qc_state=state,
        reason=reason,
    )


def write_jsonl(path: Path, records: list[BaseModel]) -> None:
    path.write_text("".join(record.model_dump_json() + "\n" for record in records))


def import_dataset(raw_path: Path, output: Path) -> dict[str, object]:
    raw = verify_file(raw_path, DATA_SHA256)
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite snapshot: {output}")
    candidates: list[Candidate] = []
    observations: list[Observation] = []
    rejected: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    seen_reactions: set[str] = set()
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
    for line, row in enumerate(rows, start=2):
        try:
            candidate, observation = normalize_row(row, DATA_SHA256)
            if candidate.candidate_id in seen_ids:
                raise ValueError("Duplicate source identity")
            if candidate.reaction_key in seen_reactions:
                raise ValueError("Duplicate reaction identity")
        except (ValueError, KeyError) as error:
            rejected.append({"line": line, "reason": str(error), "source_row": row})
            continue
        seen_ids.add(candidate.candidate_id)
        seen_reactions.add(candidate.reaction_key)
        candidates.append(candidate)
        observations.append(observation)
    passed = {o.candidate_id for o in observations if o.qc_state == "PASSED"}
    groups = Counter(c.group_id for c in candidates if c.candidate_id in passed)
    report: dict[str, object] = {
        "source_rows": len(rows),
        "candidates": len(candidates),
        "rejected_rows": len(rejected),
        "qc_counts": dict(Counter(o.qc_state for o in observations)),
        "eligible_groups": {k: v for k, v in sorted(groups.items()) if v >= 48},
    }
    manifest = {
        "source": "doyle2018",
        "revision": REVISION,
        "source_url": BASE_URL,
        "source_file_sha256": DATA_SHA256,
        "license": "MIT",
        "license_sha256": LICENSE_SHA256,
        "doi": "10.1126/science.aar5169",
        "normalization_version": NORMALIZATION_VERSION,
        "rdkit_version": rdBase.rdkitVersion,
        "yield_unit": "percent",
        "amine_evidence": AMINE_EVIDENCE,
        "limitations": [
            "Shared fixed amine: not strict both-substrates-OOD",
            "Cross-source near-duplicate normalization not implemented",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary:
        staging = Path(temporary) / "snapshot"
        staging.mkdir()
        (staging / "oracle").mkdir(mode=0o700)
        write_jsonl(staging / "candidates.jsonl", list(candidates))
        write_jsonl(staging / "oracle/observations.jsonl", list(observations))
        os.chmod(staging / "oracle/observations.jsonl", 0o600)
        # Rejected raw rows contain yields and belong exclusively to the oracle partition.
        (staging / "oracle/rejected.json").write_text(json.dumps(rejected, indent=2) + "\n")
        (staging / "quality_report.json").write_text(json.dumps(report, indent=2) + "\n")
        manifest["artifact_hashes"] = {
            str(p.relative_to(staging)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(staging.rglob("*"))
            if p.is_file()
        }
        (staging / "source_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        staging.rename(output)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw/doyle2018"))
    parser.add_argument("--output", type=Path, default=Path("data/snapshots/doyle2018-v1"))
    parser.add_argument(
        "--download", action="store_true", help="Explicitly fetch pinned public files"
    )
    args = parser.parse_args()
    if args.download:
        fetch_verified(args.raw_dir, "data_table.csv", DATA_SHA256)
        fetch_verified(args.raw_dir, "LICENSE.txt", LICENSE_SHA256)
    verify_file(args.raw_dir / "LICENSE.txt", LICENSE_SHA256)
    print(json.dumps(import_dataset(args.raw_dir / "data_table.csv", args.output), indent=2))


if __name__ == "__main__":
    main()
