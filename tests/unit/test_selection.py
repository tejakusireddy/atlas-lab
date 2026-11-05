import pytest
from atlas_optimization.selection import random_batch, ranked_batch
from hypothesis import given
from hypothesis import strategies as st


@given(st.integers(min_value=8, max_value=100), st.integers(min_value=0, max_value=10000))
def test_selection_is_unique_seeded_and_without_replacement(size: int, seed: int) -> None:
    pool = [str(i) for i in range(size)]
    chosen = random_batch(pool, [], size, 8, seed)
    assert chosen == random_batch(list(reversed(pool)), [], size, 8, seed)
    assert len(set(chosen)) == 8
    if size >= 16:
        assert not set(random_batch(pool, chosen, size, 8, seed)) & set(chosen)


def test_budget_and_unknown_selections_are_rejected() -> None:
    with pytest.raises(ValueError, match="budget"):
        random_batch(["a", "b"], ["a"], 1, 1, 42)
    with pytest.raises(ValueError, match="outside"):
        random_batch(["a"], ["unknown"], 2, 1, 42)


def test_ranking_has_stable_ties_and_rejects_nonfinite_scores() -> None:
    assert ranked_batch(["b", "a"], [], 2, 2, {"a": 1, "b": 1}) == ["a", "b"]
    with pytest.raises(ValueError, match="finite"):
        ranked_batch(["a"], [], 1, 1, {"a": float("nan")})
