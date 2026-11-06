"""Real subprocess death and post-simulation acknowledgement loss."""

from pathlib import Path
from uuid import uuid4

import pytest
from atlas_campaigns.database import Connection
from atlas_campaigns.execution import claim_next, enqueue_simulation, reconcile, recover_expired
from atlas_campaigns.models import CreateCampaign
from atlas_campaigns.service import Conflict, create_campaign
from atlas_campaigns.workflow import DecisionCommand, ProposeCommand, decide_batch, propose_batch

from tests.support import crash_dispatch


@pytest.mark.parametrize("phase", ["before_simulation", "lost_ack", "database_disconnect"])
def test_process_loss_never_redispatches(database: Connection, tmp_path: Path, phase: str) -> None:
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
    rid = batch["run_id"]
    enqueue_simulation(database, rid, 0, "scientist", "dispatch", uuid4(), "trace")
    process = crash_dispatch(database, tmp_path, phase)
    assert process.returncode != 0
    run = database.execute("SELECT * FROM experiment_runs WHERE id=%s", (rid,)).fetchone()
    assert run is not None and run["status"] == "SIMULATING"
    assert claim_next(database, tmp_path) is None
    database.execute(
        "UPDATE experiment_runs SET lease_until=now()-interval '1 second' WHERE id=%s", (rid,)
    )
    assert recover_expired(database) == 1
    assert recover_expired(database) == 0
    with pytest.raises(Conflict):
        enqueue_simulation(database, rid, 5, "scientist", "retry", uuid4(), "trace")
    if phase == "before_simulation":
        with pytest.raises(Conflict, match="No durable"):
            reconcile(database, rid, 5, "reviewer", "recover", uuid4(), "trace")
    else:
        result = reconcile(database, rid, 5, "reviewer", "recover", uuid4(), "trace")
        assert result["status"] == "SIMULATED"
        assert reconcile(database, rid, 5, "reviewer", "recover", uuid4(), "trace")["id"] == rid
        assert database.execute(
            "SELECT * FROM execution_receipts WHERE run_id=%s", (rid,)
        ).fetchone()
    current = database.execute(
        "SELECT budget_used FROM campaigns WHERE id=%s", (campaign.id,)
    ).fetchone()
    assert current is not None and current["budget_used"] == 8
    assert claim_next(database, tmp_path) is None
