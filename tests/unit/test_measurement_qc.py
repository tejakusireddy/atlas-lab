import pytest
from atlas_measurements.oracle import quality


@pytest.mark.parametrize(
    ("change", "expected"),
    [
        ({}, "PASSED"),
        ({"observed_yield_pct": 101}, "QUARANTINED"),
        ({"raw_yield": "42"}, "QUARANTINED"),
        ({"source_kind": "synthetic_test"}, "QUARANTINED"),
        ({"source_record_id": "other"}, "QUARANTINED"),
        ({"observed_yield_pct": None, "qc_state": "UNOBSERVED"}, "UNOBSERVED"),
    ],
)
def test_only_verified_historical_values_pass(change: dict[str, object], expected: str) -> None:
    raw = {
        "candidate_id": "c",
        "source_record_id": "row1",
        "source_file_sha256": "hash",
        "source_kind": "historical_observed",
        "raw_yield": "50",
        "observed_yield_pct": 50,
        "qc_state": "PASSED",
        **change,
    }
    state, value, _ = quality(
        raw, raw | {"source_record_id": "row1"}, {"source_file_sha256": "hash"}
    )
    assert state == expected
    assert value == (50 if expected == "PASSED" else None)


def test_missing_record_is_unobserved() -> None:
    assert quality(None, {}, {})[:2] == ("UNOBSERVED", None)
