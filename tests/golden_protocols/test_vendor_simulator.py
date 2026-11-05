from pathlib import Path
from uuid import uuid4

import pytest
from atlas_instrument_gateway.simulator import simulate_plan
from atlas_instrument_gateway.spec import RunPlan, Transfer


@pytest.mark.parametrize("count", [1, 8, 96])
def test_real_vendor_simulator_accepts_compiled_work_orders(count: int, tmp_path: Path) -> None:
    candidates = tuple(f"synthetic-test-{i}" for i in range(count))
    wells = [f"{row}{column}" for column in range(1, 13) for row in "ABCDEFGH"]
    plan = RunPlan(
        campaign_id=uuid4(),
        batch_id=uuid4(),
        run_id=uuid4(),
        created_by="test",
        source_dataset_snapshot="synthetic-test",
        candidate_ids=candidates,
        transfers=tuple(
            Transfer(candidate_id=candidate, destination_well=wells[index])
            for index, candidate in enumerate(candidates)
        ),
    )
    result = simulate_plan(plan, tmp_path / "attempt")
    assert result["status"] == "SIMULATED", (tmp_path / "attempt/stderr.log").read_text()
    assert result["receipt"]["simulator_version"] == "10.1.0"
    assert result["receipt"]["protocol_hash"] == result["protocol_hash"]
    assert len(result["receipt"]["commands"]) >= count * 4
