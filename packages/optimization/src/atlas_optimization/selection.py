"""Finite-pool selection with explicit uniqueness and budget checks."""

import math
import random
from collections.abc import Mapping, Sequence


def eligible_ids(
    pool: Sequence[str], selected: Sequence[str], budget: int, count: int
) -> list[str]:
    if budget < 1 or count < 1:
        raise ValueError("Budget and batch count must be positive")
    if len(set(pool)) != len(pool) or len(set(selected)) != len(selected):
        raise ValueError("Duplicate candidate IDs")
    if not set(selected).issubset(pool):
        raise ValueError("Selection outside frozen pool")
    if len(selected) + count > budget:
        raise ValueError("Experiment budget exceeded")
    remaining = sorted(set(pool) - set(selected))
    if count > len(remaining):
        raise ValueError("Insufficient unselected candidates")
    return remaining


def random_batch(
    pool: Sequence[str], selected: Sequence[str], budget: int, count: int, seed: int
) -> list[str]:
    remaining = eligible_ids(pool, selected, budget, count)
    return random.Random(seed).sample(remaining, count)


def ranked_batch(
    pool: Sequence[str],
    selected: Sequence[str],
    budget: int,
    count: int,
    scores: Mapping[str, float],
) -> list[str]:
    remaining = eligible_ids(pool, selected, budget, count)
    if any(
        candidate not in scores or not math.isfinite(scores[candidate]) for candidate in remaining
    ):
        raise ValueError("Every eligible candidate requires a finite score")
    return sorted(remaining, key=lambda candidate: (-scores[candidate], candidate))[:count]
