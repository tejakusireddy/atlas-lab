"""Typed scientific inputs; outcomes are stored in a separate record type."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Molecule(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    role: Literal["aryl", "amine", "base", "ligand", "additive"]
    original_smiles: str
    canonical_smiles: str


class Candidate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    candidate_id: str
    reaction_key: str
    group_id: str
    source_record_id: str
    source_file_sha256: str
    molecules: tuple[Molecule, ...]


class Observation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    candidate_id: str
    source_record_id: str
    source_file_sha256: str
    source_kind: Literal["historical_observed", "synthetic_test"]
    raw_yield: str
    observed_yield_pct: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    qc_state: Literal["PASSED", "QUARANTINED", "UNOBSERVED"]
    reason: str | None = None
