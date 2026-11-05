"""Outcome-free, role-separated Morgan fingerprints."""

from collections.abc import Sequence
from functools import lru_cache

import numpy as np
from numpy.typing import NDArray
from rdkit import Chem
from rdkit.Chem import rdFingerprintGenerator

from atlas_science.records import Candidate

FEATURE_VERSION = "morgan-role-v1-radius2-bits256"
ROLE_ORDER = ("aryl", "amine", "base", "ligand", "additive")


@lru_cache(maxsize=4096)
def fingerprint(smiles: str) -> tuple[float, ...]:
    if not smiles:
        return (0.0,) * 256
    molecule = Chem.MolFromSmiles(smiles)
    if molecule is None:
        raise ValueError("Invalid canonical molecule")
    generator = rdFingerprintGenerator.GetMorganGenerator(radius=2, fpSize=256)
    return tuple(float(x) for x in generator.GetFingerprintAsNumPy(molecule))


def feature_matrix(candidates: Sequence[Candidate]) -> NDArray[np.float64]:
    rows = []
    for candidate in candidates:
        roles: dict[str, str] = {m.role: m.canonical_smiles for m in candidate.molecules}
        if set(roles) != set(ROLE_ORDER) or len(candidate.molecules) != len(ROLE_ORDER):
            raise ValueError("Feature schema requires exactly one molecule per role")
        rows.append([value for role in ROLE_ORDER for value in fingerprint(roles[role])])
    return np.asarray(rows, dtype=np.float64).reshape(len(candidates), 256 * len(ROLE_ORDER))
