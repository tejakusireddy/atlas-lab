import json
import os
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from atlas_campaigns.broker import (
    LOCK_ID,
    BrokerConfig,
    dispatch_once,
    process_reconciliation,
    validate_dispatch_role,
)
from atlas_campaigns.database import Connection
from atlas_campaigns.execution import (
    claim_next,
    enqueue_simulation,
    request_reconciliation,
    transition,
)
from atlas_campaigns.permissions import validate_application_role
from atlas_campaigns.secrets import ConfigurationError
from atlas_campaigns.service import Conflict
from atlas_instrument_gateway.compiler import compile_protocol
from atlas_measurements.oracle import reveal

from tests.integration.test_database_permissions import runtime_roles as runtime_roles
from tests.integration.test_execution import approved_run

pytestmark = pytest.mark.integration


def test_broker_claims_only_approved_intents_and_replay_does_not_execute(
    runtime_roles: dict[str, Connection],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    database: Connection,
) -> None:
    application, dispatch = runtime_roles["application"], runtime_roles["dispatch"]
    validate_dispatch_role(dispatch)
    validate_application_role(application)
    with pytest.raises(ConfigurationError):
        validate_application_role(dispatch)
    for profile in ("application", "release"):
        with pytest.raises(ConfigurationError):
            validate_dispatch_role(runtime_roles[profile])
    config = BrokerConfig(tmp_path, tmp_path / "socket", "sha256:" + "a" * 64, "daemon-1234")
    monkeypatch.setattr(BrokerConfig, "inspect_engine", Mock())
    monkeypatch.setattr(BrokerConfig, "slot_available", Mock(return_value=True))
    # The simulator is stubbed here; vendor/container execution has separate golden/fault suites.
    simulator = Mock(
        side_effect=lambda plan, output, **kwargs: {
            "status": "SIMULATED",
            "receipt": {
                "run_id": str(plan.run_id),
                "protocol_hash": compile_protocol(plan).protocol_hash,
                "simulator_version": "10.1.0",
                "status": "SIMULATED",
            },
        }
    )
    monkeypatch.setattr("atlas_campaigns.broker.simulate_plan", simulator)
    database.execute("SELECT pg_advisory_lock(%s)", (LOCK_ID,))
    try:
        assert dispatch_once(dispatch, config) is None
        assert simulator.call_count == 0
    finally:
        database.execute("SELECT pg_advisory_unlock(%s)", (LOCK_ID,))
    assert dispatch_once(dispatch, config) is None
    run_id = approved_run(application)
    assert dispatch_once(dispatch, config) is None  # Approval alone is not dispatch intent.
    enqueue_simulation(application, run_id, 0, "scientist", "dispatch", uuid4(), "trace")
    monkeypatch.setattr(BrokerConfig, "slot_available", Mock(return_value=False))
    assert dispatch_once(dispatch, config) is None
    pending = application.execute(
        "SELECT status,attempt_id FROM experiment_runs WHERE id=%s", (run_id,)
    ).fetchone()
    assert pending is not None and pending["status"] == "DISPATCH_PENDING"
    assert pending["attempt_id"] is None
    monkeypatch.setattr(BrokerConfig, "slot_available", Mock(return_value=True))
    result = dispatch_once(dispatch, config)
    assert result is not None and result["status"] == "SIMULATED"
    assert dispatch_once(dispatch, config) is None
    assert simulator.call_count == 1
    assert simulator.call_args.kwargs == {
        "image": config.image_id,
        "docker_host": config.docker_host,
        "container_name": "atlas-dispatch-slot",
    }
    assert simulator.call_args.args[1] == tmp_path / str(run_id)


def test_broker_reconciliation_is_queued_deduplicated_and_retryable(
    runtime_roles: dict[str, Connection], tmp_path: Path
) -> None:
    application, dispatch = runtime_roles["application"], runtime_roles["dispatch"]
    run_id = approved_run(application)
    enqueue_simulation(application, run_id, 0, "scientist", "dispatch", uuid4(), "trace")
    run = claim_next(dispatch, tmp_path)
    assert run is not None
    unknown = transition(dispatch, run, "EXECUTION_UNKNOWN", "trace")
    request_reconciliation(
        application, run_id, unknown["version"], "reviewer", "first", uuid4(), "trace"
    )
    request_reconciliation(
        application, run_id, unknown["version"], "reviewer", "again", uuid4(), "trace"
    )
    assert len(list(application.execute("SELECT * FROM reconciliation_requests"))) == 1
    assert process_reconciliation(dispatch, tmp_path)
    result = application.execute("SELECT * FROM reconciliation_results").fetchone()
    assert result is not None and result["status"] == "FAILED"
    assert not process_reconciliation(dispatch, tmp_path)
    receipt = tmp_path / str(run_id) / "receipt/receipt.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(
        json.dumps(
            {
                "run_id": str(run_id),
                "protocol_hash": run["protocol_hash"],
                "simulator_version": "10.1.0",
                "status": "SIMULATED",
            }
        )
    )
    request_reconciliation(
        application, run_id, unknown["version"], "reviewer", "retry", uuid4(), "trace"
    )
    assert process_reconciliation(dispatch, tmp_path)
    assert not process_reconciliation(dispatch, tmp_path)
    assert len(list(application.execute("SELECT * FROM execution_receipts"))) == 1
    assert len(list(application.execute("SELECT * FROM reconciliation_requests"))) == 2
    row = application.execute(
        "SELECT status FROM experiment_runs WHERE id=%s", (run_id,)
    ).fetchone()
    assert row is not None and row["status"] == "SIMULATED"


def test_status_change_cannot_unlock_private_outcomes_without_broker_receipt(
    runtime_roles: dict[str, Connection], tmp_path: Path
) -> None:
    application, dispatch = runtime_roles["application"], runtime_roles["dispatch"]
    run_id = approved_run(application)
    enqueue_simulation(application, run_id, 0, "scientist", "dispatch", uuid4(), "trace")
    assert claim_next(dispatch, tmp_path) is not None
    application.execute("UPDATE experiment_runs SET status='SIMULATED' WHERE id=%s", (run_id,))
    with pytest.raises(Conflict, match="Verified successful execution receipt"):
        reveal(runtime_roles["release"], UUID(str(run_id)), tmp_path / "absent-oracle")


@pytest.mark.parametrize("invalid_receipt", ["symlink", "oversized", "malformed", "fifo"])
def test_reconciliation_rejects_untrusted_artifacts(
    runtime_roles: dict[str, Connection], tmp_path: Path, invalid_receipt: str
) -> None:
    application, dispatch = runtime_roles["application"], runtime_roles["dispatch"]
    root = tmp_path / "private"
    root.mkdir()
    run_id = approved_run(application)
    enqueue_simulation(application, run_id, 0, "scientist", "dispatch", uuid4(), "trace")
    run = claim_next(dispatch, root)
    assert run is not None
    unknown = transition(dispatch, run, "EXECUTION_UNKNOWN", "trace")
    receipt = root / str(run_id) / "receipt/receipt.json"
    receipt.parent.mkdir(parents=True)
    if invalid_receipt == "symlink":
        outside = tmp_path / "outside.json"
        outside.write_text(
            json.dumps(
                {
                    "run_id": str(run_id),
                    "protocol_hash": run["protocol_hash"],
                    "simulator_version": "10.1.0",
                    "status": "SIMULATED",
                }
            )
        )
        receipt.symlink_to(outside)
    elif invalid_receipt == "fifo":
        os.mkfifo(receipt)
    else:
        receipt.write_text("x" * 65537 if invalid_receipt == "oversized" else "{")
    request_reconciliation(
        application, run_id, unknown["version"], "reviewer", "request", uuid4(), "trace"
    )
    assert process_reconciliation(dispatch, root)
    assert not list(application.execute("SELECT * FROM execution_receipts"))
    result = application.execute("SELECT * FROM reconciliation_results").fetchone()
    assert result is not None and result["reason"] == "receipt_unavailable_or_invalid"
