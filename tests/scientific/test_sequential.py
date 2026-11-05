import numpy as np
import pytest
from atlas_science.benchmark import POLICIES, choose_indices


def test_every_policy_selects_only_unobserved_candidates() -> None:
    features = np.random.default_rng(0).random((24, 10))
    for policy in POLICIES:
        selected = choose_indices(
            policy,
            features,
            list(range(8)),
            np.arange(8.0),
            features[:0],
            np.array([], dtype=float),
            42,
        )
        assert len(set(selected)) == 8
        assert not set(selected) & set(range(8))
        assert selected == choose_indices(
            policy,
            features,
            list(range(8)),
            np.arange(8.0),
            features[:0],
            np.array([], dtype=float),
            42,
        )


def test_policy_rejects_hidden_labels() -> None:
    with pytest.raises(ValueError, match="Observed labels"):
        choose_indices(
            "greedy",
            np.ones((24, 10)),
            [0],
            np.arange(24.0),
            np.ones((0, 10)),
            np.array([], dtype=float),
            42,
        )
