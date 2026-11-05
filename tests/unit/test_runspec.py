from uuid import uuid4

import pytest
from atlas_instrument_gateway.compiler import compile_protocol
from atlas_instrument_gateway.spec import RunPlan, Transfer
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError


def plan() -> RunPlan:
    return RunPlan(
        campaign_id=uuid4(),
        batch_id=uuid4(),
        run_id=uuid4(),
        source_dataset_snapshot="synthetic-test",
        created_by="scientist",
        candidate_ids=("candidate-1",),
        transfers=(Transfer(candidate_id="candidate-1", destination_well="A1"),),
    )


@given(st.floats(max_value=0, allow_nan=False, allow_infinity=False))
def test_invalid_volumes_are_rejected(volume: float) -> None:
    with pytest.raises(ValidationError):
        Transfer(candidate_id="test", destination_well="A1", volume_ul=volume)


@pytest.mark.parametrize(
    "changes",
    [
        {"execution_mode": "physical"},
        {"source_slot": "A3"},
        {"source_slot": "D2"},
        {"candidate_ids": ("candidate-1", "candidate-1")},
        {"source_available_ul": 500.0},
        {"pipette": "arbitrary"},
        {"code": "print(1)"},
    ],
)
def test_unsafe_or_unsupported_spec_is_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        RunPlan.model_validate({**plan().model_dump(), **changes})


def test_hash_binds_transfer_and_compiler_revalidates() -> None:
    original = plan()
    artifact = compile_protocol(original)
    assert artifact == compile_protocol(original)
    changed = RunPlan.model_validate(
        {
            **original.model_dump(),
            "transfers": [
                {"candidate_id": "candidate-1", "destination_well": "B1", "volume_ul": 50.0}
            ],
        }
    )
    assert changed.plan_hash() != original.plan_hash()
    assert compile_protocol(changed).protocol_hash != artifact.protocol_hash
    with pytest.raises(ValidationError):
        compile_protocol(original.model_copy(update={"execution_mode": "physical"}))
