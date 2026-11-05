import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from atlas_campaigns.database import Connection
from atlas_campaigns.execution import claim_next, enqueue_simulation, reconcile, recover_expired
from atlas_campaigns.models import CreateCampaign
from atlas_campaigns.service import Conflict, create_campaign
from atlas_campaigns.workflow import DecisionCommand, ProposeCommand, decide_batch, propose_batch

pytestmark = pytest.mark.integration


def approved_run(database: Connection) -> UUID:
    campaign = create_campaign(
        database,
        CreateCampaign(
            dataset_snapshot_id="synthetic-snapshot", campaign_group_id="synthetic-group"
        ),
        "scientist",
        "create",
        uuid4(),
        "trace",
    )
    batch = propose_batch(
        database,
        campaign.id,
        ProposeCommand(expected_version=0),
        "scientist",
        "plan",
        uuid4(),
        "trace",
    )
    decide_batch(
        database,
        campaign.id,
        batch["id"],
        DecisionCommand(expected_version=0, plan_hash=batch["plan_hash"]),
        "APPROVE",
        "reviewer",
        "reviewer",
        "approve",
        uuid4(),
        "trace",
    )
    return UUID(str(batch["run_id"]))


def test_dispatch_is_deduplicated_and_lease_loss_requires_reconciliation(
    database: Connection, tmp_path: Path
) -> None:
    run_id = approved_run(database)
    pending = enqueue_simulation(database, run_id, 0, "scientist", "dispatch", uuid4(), "trace")
    assert pending["status"] == "DISPATCH_PENDING"
    duplicate = enqueue_simulation(database, run_id, 0, "scientist", "dispatch", uuid4(), "trace")
    assert duplicate["id"] == run_id
    claimed = claim_next(database, tmp_path)
    assert claimed is not None and claimed["status"] == "SIMULATING"
    assert claim_next(database, tmp_path) is None
    database.execute(
        "UPDATE experiment_runs SET lease_until=now()-interval '1 minute' WHERE id=%s", (run_id,)
    )
    assert recover_expired(database) == 1
    with pytest.raises(Conflict):
        enqueue_simulation(database, run_id, 5, "scientist", "retry", uuid4(), "trace")
    with pytest.raises(Conflict, match="No durable"):
        reconcile(database, run_id, 5, "reviewer", "reconcile", uuid4(), "trace")
    directory = Path(claimed["artifact_directory"]) / "receipt"
    directory.mkdir(parents=True)
    for invalid in ("{", "[]"):
        (directory / "receipt.json").write_text(invalid)
        with pytest.raises(Conflict, match="Durable receipt"):
            reconcile(database, run_id, 5, "reviewer", "reconcile", uuid4(), "trace")
    (directory / "receipt.json").write_text(
        json.dumps(
            {
                "run_id": str(run_id),
                "status": "SIMULATED",
                "protocol_hash": claimed["protocol_hash"],
                "simulator_version": "10.1.0",
                "source_kind": "synthetic_test",
            }
        )
    )
    result = reconcile(database, run_id, 5, "reviewer", "reconcile", uuid4(), "trace")
    assert result["status"] == "SIMULATED"
    events = list(
        database.execute(
            "SELECT sequence FROM run_events WHERE run_id=%s ORDER BY sequence", (run_id,)
        )
    )
    assert [event["sequence"] for event in events] == list(range(1, 8))


def test_expired_approval_blocks_dispatch(
    database: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import UTC, datetime, timedelta

    run_id = approved_run(database)

    class FutureClock:
        @classmethod
        def now(cls, tz: object = None) -> datetime:
            return datetime.now(UTC) + timedelta(hours=2)

    monkeypatch.setattr("atlas_campaigns.execution.datetime", FutureClock)
    with pytest.raises(Conflict, match="expired"):
        enqueue_simulation(database, run_id, 0, "scientist", "dispatch", uuid4(), "trace")
    row = database.execute("SELECT status FROM experiment_runs WHERE id=%s", (run_id,)).fetchone()
    assert row is not None and row["status"] == "APPROVED"
