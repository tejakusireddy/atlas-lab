"""Deterministic group partitions with explicit leakage assertions."""

import random
from collections import defaultdict
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from atlas_science.records import Candidate


class SplitManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    seed: int
    strategy: str = "substrate-pair-held-out-v1"
    train_ids: tuple[str, ...]
    calibration_ids: tuple[str, ...]
    campaign_ids: tuple[str, ...]
    ood_test_ids: tuple[str, ...]


def assert_disjoint(
    partitions: Sequence[Sequence[Candidate]], strict_substrates: bool = False
) -> None:
    """Reject overlap by source ID, canonical reaction, or substrate-pair identity."""
    seen_ids: set[str] = set()
    seen_reactions: set[str] = set()
    seen_groups: set[str] = set()
    seen_substrates: set[str] = set()
    for partition in partitions:
        ids = {c.candidate_id for c in partition}
        reactions = {c.reaction_key for c in partition}
        groups = {c.group_id for c in partition}
        substrates = {
            m.canonical_smiles
            for c in partition
            for m in c.molecules
            if m.role in ("aryl", "amine")
        }
        if len(ids) != len(partition) or len(reactions) != len(partition):
            raise ValueError("Duplicate candidate or reaction within partition")
        if ids & seen_ids or reactions & seen_reactions or groups & seen_groups:
            raise ValueError("Data leakage across partitions")
        if strict_substrates and substrates & seen_substrates:
            raise ValueError("Shared substrate violates strict OOD")
        seen_ids.update(ids)
        seen_reactions.update(reactions)
        seen_groups.update(groups)
        seen_substrates.update(substrates)


def create_split(candidates: Sequence[Candidate], seed: int = 42) -> SplitManifest:
    groups: dict[str, list[Candidate]] = defaultdict(list)
    for candidate in candidates:
        groups[candidate.group_id].append(candidate)
    if len(groups) < 4:
        raise ValueError("At least four substrate groups are required")
    ordered = sorted(groups)
    random.Random(seed).shuffle(ordered)
    holdout_count = max(1, len(ordered) // 5)
    # Fixed independent partitions; no outcome is consulted to choose them.
    assigned = [
        ordered[:holdout_count],
        ordered[holdout_count : 2 * holdout_count],
        ordered[2 * holdout_count : 3 * holdout_count],
        ordered[3 * holdout_count :],
    ]
    calibration, campaign, ood, train = [
        sorted((c for group in keys for c in groups[group]), key=lambda c: c.candidate_id)
        for keys in assigned
    ]
    assert_disjoint([train, calibration, campaign, ood])
    return SplitManifest(
        seed=seed,
        train_ids=tuple(c.candidate_id for c in train),
        calibration_ids=tuple(c.candidate_id for c in calibration),
        campaign_ids=tuple(c.candidate_id for c in campaign),
        ood_test_ids=tuple(c.candidate_id for c in ood),
    )
