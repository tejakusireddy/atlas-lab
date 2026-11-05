"""Local verification fixture with scripted demo identities; creates a new campaign."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

from atlas_campaigns.analysis import analyze
from atlas_campaigns.database import connect
from atlas_campaigns.execution import enqueue_simulation, execute_next
from atlas_campaigns.models import CreateCampaign
from atlas_campaigns.service import create_campaign
from atlas_campaigns.workflow import DecisionCommand, ProposeCommand, decide_batch, propose_batch
from atlas_measurements.oracle import reveal
from atlas_science.records import Candidate
from atlas_science.splits import create_split

snapshot = Path("data/snapshots/doyle2018-v1")
candidates = [
    Candidate.model_validate_json(line)
    for line in (snapshot / "candidates.jsonl").read_text().splitlines()
]
split = create_split(candidates)
group = next(c.group_id for c in candidates if c.candidate_id == split.campaign_ids[0])
trace = uuid4().hex
with connect() as db:
    digest = (
        "sha256:" + hashlib.sha256((snapshot / "source_manifest.json").read_bytes()).hexdigest()
    )
    registry = db.execute(
        "SELECT id FROM dataset_snapshots WHERE manifest_hash=%s", (digest,)
    ).fetchone()
    if registry is None:
        raise RuntimeError("Register the local Doyle snapshot before verification")
    pending = db.execute(
        "SELECT id FROM outbox_events WHERE published_at IS NULL "
        "AND event_type='run.dispatch_requested' LIMIT 1"
    ).fetchone()
    if pending is not None:
        raise RuntimeError("Drain the dispatch queue before verification")
    campaign = create_campaign(
        db,
        CreateCampaign(dataset_snapshot_id=registry["id"], campaign_group_id=group),
        "local-scientist",
        trace,
        uuid4(),
        trace,
    )
    summary = {"campaign_id": str(campaign.id), "group_id": group, "split_seed": 42, "batches": []}
    for index in range(6):
        state = db.execute("SELECT * FROM campaigns WHERE id=%s", (campaign.id,)).fetchone()
        batch = propose_batch(
            db,
            campaign.id,
            ProposeCommand(expected_version=state["version"]),
            "local-scientist",
            f"{trace}-plan-{index}",
            uuid4(),
            trace,
        )
        decide_batch(
            db,
            campaign.id,
            batch["id"],
            DecisionCommand(expected_version=0, plan_hash=batch["plan_hash"]),
            "APPROVE",
            "local-reviewer",
            "reviewer",
            f"{trace}-approve-{index}",
            uuid4(),
            trace,
        )
        enqueue_simulation(
            db, batch["run_id"], 0, "local-scientist", f"{trace}-dispatch-{index}", uuid4(), trace
        )
        result = execute_next(db, Path("artifacts/runs"))
        assert (
            result is not None
            and result["id"] == batch["run_id"]
            and result["status"] == "SIMULATED"
        ), result
        rows = reveal(db, batch["run_id"], snapshot)
        assert len(rows) == 8 and all(r["qc_state"] == "PASSED" for r in rows)
        run = db.execute("SELECT * FROM experiment_runs WHERE id=%s", (batch["run_id"],)).fetchone()
        analysis = analyze(
            db,
            batch["run_id"],
            run["version"],
            "local-scientist",
            f"{trace}-analyze-{index}",
            uuid4(),
            trace,
        )
        summary["batches"].append(
            {
                "run_id": str(batch["run_id"]),
                "analysis_hash": analysis["snapshot_hash"],
                "observed_count": len(analysis["snapshot"]["observations"]),
                "best_observed": analysis["snapshot"]["best_observed"],
            }
        )
        print(
            json.dumps({"batch": index + 1, "observed": len(analysis["snapshot"]["observations"])}),
            flush=True,
        )
    state = db.execute(
        "SELECT status,budget_used FROM campaigns WHERE id=%s", (campaign.id,)
    ).fetchone()
    assert state == {"status": "COMPLETE", "budget_used": 48}, state
    summary["status"] = state
    output = Path("artifacts/closed-loop-verification.json")
    output.write_text(json.dumps(summary, indent=2))
    print(str(output))
