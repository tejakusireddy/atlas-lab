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


def test_broker_launch_pins_engine_image_slot_and_sandbox(tmp_path: Path) -> None:
    from unittest.mock import Mock

    plan = RunPlan(
        campaign_id=uuid4(),
        batch_id=uuid4(),
        run_id=uuid4(),
        created_by="test",
        source_dataset_snapshot="synthetic-test",
        candidate_ids=("test-1",),
        transfers=(Transfer(candidate_id="test-1", destination_well="A1"),),
    )
    image = "sha256:" + "a" * 64
    host = "unix:///run/atlas-dispatch/docker.sock"
    with (
        patch("atlas_instrument_gateway.simulator.subprocess.check_output", return_value=image),
        patch(
            "atlas_instrument_gateway.simulator.subprocess.run",
            return_value=Mock(returncode=1, stdout="", stderr="failed"),
        ) as execute,
    ):
        result = simulate_plan(
            plan,
            tmp_path / "attempt",
            image=image,
            docker_host=host,
            container_name="atlas-dispatch-slot",
        )
    assert result["status"] == "EXECUTION_FAILED"
    command = execute.call_args.args[0]
    assert command[:4] == ["docker", "--host", host, "run"]
    assert command[-1] == image and command[command.index("--name") + 1] == "atlas-dispatch-slot"
    assert {
        "--network=none",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--memory=1g",
        "--cpus=1",
        "--pids-limit=128",
    } <= set(command)
    assert len([argument for argument in command if argument.startswith("type=bind,")]) == 2
    assert not any("docker.sock" in argument for argument in command[4:])
    assert not any("--env" in argument or "--privileged" in argument for argument in command)


def test_pinned_image_mismatch_fails_before_creating_artifacts(tmp_path: Path) -> None:
    import pytest

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
            "atlas_instrument_gateway.simulator.subprocess.check_output",
            return_value="sha256:" + "b" * 64,
        ),
        pytest.raises(ValueError, match="identity"),
    ):
        simulate_plan(plan, tmp_path / "attempt", image="sha256:" + "a" * 64)
    assert not (tmp_path / "attempt").exists()
