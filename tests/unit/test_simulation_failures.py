import json
import subprocess
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from atlas_instrument_gateway.simulator import simulate_plan
from atlas_instrument_gateway.spec import RunPlan, Transfer


def test_timeout_retains_unknown_state_without_redispatch(tmp_path: Path) -> None:
    plan = RunPlan(
        campaign_id=uuid4(),
        batch_id=uuid4(),
        run_id=uuid4(),
        created_by="test",
        source_dataset_snapshot="synthetic-test",
        candidate_ids=("test-1",),
        transfers=(Transfer(candidate_id="test-1", destination_well="A1"),),
    )
    with (
        patch(
            "atlas_instrument_gateway.simulator.subprocess.check_output", return_value="sha256:test"
        ),
        patch(
            "atlas_instrument_gateway.simulator.subprocess.run",
            side_effect=subprocess.TimeoutExpired("docker", 1),
        ) as execute,
    ):
        result = simulate_plan(plan, tmp_path / "attempt", timeout=1)
    assert result["status"] == "EXECUTION_UNKNOWN"
    assert execute.call_count == 1
    saved = json.loads((tmp_path / "attempt/simulation_manifest.json").read_text())
    assert saved["status"] == "EXECUTION_UNKNOWN"
    assert (tmp_path / "attempt/protocol.py").exists()
    assert (tmp_path / "attempt/run_spec.json").exists()
