import math

import pytest
from atlas_domain.hashing import canonical_json, content_hash


def test_hash_is_independent_of_mapping_order_but_binds_values() -> None:
    assert content_hash({"a": 1, "b": [2, 3]}) == content_hash({"b": [2, 3], "a": 1})
    assert content_hash({"a": 1}) != content_hash({"a": 2})
    assert content_hash([1, 2]) != content_hash([2, 1])


def test_encoding_has_explicit_unicode_and_numeric_semantics() -> None:
    assert canonical_json({"label": "μL", "volume": 1.0}) == '{"label":"μL","volume":1.0}'.encode()
    assert content_hash(1) != content_hash(1.0)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_nonfinite_values_cannot_enter_artifact_hashes(value: float) -> None:
    with pytest.raises(ValueError):
        content_hash({"yield": value})
