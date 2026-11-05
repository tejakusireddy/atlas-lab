from uuid import uuid4

import psycopg
import pytest
from atlas_campaigns.database import Connection
from atlas_campaigns.models import CreateCampaign
from atlas_campaigns.service import Conflict, create_campaign, get_campaign
from atlas_campaigns.workflow import (
    DecisionCommand,
    Forbidden,
    ProposeCommand,
    decide_batch,
    propose_batch,
)

pytestmark = pytest.mark.integration


def test_proposal_approval_and_budget_reservation(database: Connection) -> None:
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
    assert batch["status"] == "AWAITING_APPROVAL"
    assert len(batch["run_spec"]["candidate_ids"]) == 8
    repeated = propose_batch(
        database,
        campaign.id,
        ProposeCommand(expected_version=0),
        "scientist",
        "plan",
        uuid4(),
        "trace",
    )
    assert repeated["id"] == batch["id"]
    command = DecisionCommand(expected_version=0, plan_hash=batch["plan_hash"])
    with pytest.raises(Forbidden):
        decide_batch(
            database,
            campaign.id,
            batch["id"],
            command,
            "APPROVE",
            "scientist",
            "reviewer",
            "self",
            uuid4(),
            "trace",
        )
    with pytest.raises(Conflict, match="immutable"):
        decide_batch(
            database,
            campaign.id,
            batch["id"],
            command.model_copy(update={"plan_hash": "sha256:" + "0" * 64}),
            "APPROVE",
            "reviewer",
            "reviewer",
            "bad",
            uuid4(),
            "trace",
        )
    approved = decide_batch(
        database,
        campaign.id,
        batch["id"],
        command,
        "APPROVE",
        "reviewer",
        "reviewer",
        "approve",
        uuid4(),
        "trace",
    )
    assert approved["status"] == "APPROVED"
    duplicate = decide_batch(
        database,
        campaign.id,
        batch["id"],
        command,
        "APPROVE",
        "reviewer",
        "reviewer",
        "approve",
        uuid4(),
        "trace",
    )
    assert duplicate["id"] == approved["id"]
    updated = get_campaign(database, campaign.id, "scientist")
    assert updated.budget_used == 8
    assert updated.status == "ACTIVE"
    count = database.execute("SELECT count(*) AS n FROM campaign_selections").fetchone()
    assert count is not None and count["n"] == 8
    with pytest.raises(Conflict):
        propose_batch(
            database,
            campaign.id,
            ProposeCommand(expected_version=updated.version),
            "scientist",
            "another",
            uuid4(),
            "trace",
        )
    with pytest.raises(psycopg.errors.RaiseException, match="immutable"):
        database.execute(
            "UPDATE experiment_batches SET plan_hash=%s WHERE id=%s",
            ("sha256:" + "1" * 64, batch["id"]),
        )


def test_rejection_allows_new_plan_without_spending_budget(database: Connection) -> None:
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
        "REJECT",
        "reviewer",
        "reviewer",
        "reject",
        uuid4(),
        "trace",
    )
    assert get_campaign(database, campaign.id, "scientist").budget_used == 0
    revised = propose_batch(
        database,
        campaign.id,
        ProposeCommand(expected_version=1),
        "scientist",
        "revised",
        uuid4(),
        "trace",
    )
    assert revised["id"] != batch["id"]
    assert revised["plan_hash"] != batch["plan_hash"]
