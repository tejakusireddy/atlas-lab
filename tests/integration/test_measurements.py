import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest
from atlas_campaigns.analysis import analyze
from atlas_campaigns.database import Connection, connect
from atlas_campaigns.execution import claim_next, enqueue_simulation, record_receipt, transition
from atlas_campaigns.models import CreateCampaign
from atlas_campaigns.service import Conflict, create_campaign
from atlas_campaigns.workflow import DecisionCommand, ProposeCommand, decide_batch, propose_batch
from atlas_measurements.oracle import reveal
from psycopg import sql
from psycopg.types.json import Jsonb

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("include_records", [True, False])
def test_release_gating_idempotency_and_no_synthetic_training(
    database: Connection, tmp_path: Path, include_records: bool
) -> None:
    records = (
        b"\n".join(
            json.dumps(
                {
                    "candidate_id": f"test-{i}",
                    "source_record_id": str(i),
                    "source_file_sha256": "fixture",
                    "source_kind": "synthetic_test",
                    "raw_yield": "50",
                    "observed_yield_pct": 50,
                    "qc_state": "PASSED",
                }
            ).encode()
            for i in range(48)
        )
        if include_records
        else b""
    )
    manifest = {
        "source_file_sha256": "fixture",
        "yield_unit": "percent",
        "doi": "synthetic-test",
        "artifact_hashes": {"oracle/observations.jsonl": hashlib.sha256(records).hexdigest()},
    }
    manifest_bytes = json.dumps(manifest).encode()
    (tmp_path / "oracle").mkdir()
    oracle = tmp_path / "oracle/observations.jsonl"
    oracle.write_bytes(records)
    (tmp_path / "source_manifest.json").write_bytes(manifest_bytes)
    database.execute(
        "INSERT INTO dataset_snapshots(id,manifest_hash) VALUES ('oracle-test',%s)",
        ("sha256:" + hashlib.sha256(manifest_bytes).hexdigest(),),
    )
    database.execute("INSERT INTO dataset_groups VALUES ('oracle-test','test',48)")
    for i in range(48):
        database.execute(
            """INSERT INTO dataset_candidates VALUES ('oracle-test',%s,'test',%s,%s)""",
            (
                f"test-{i}",
                f"reaction-{i}",
                Jsonb({"source_record_id": str(i), "source_file_sha256": "fixture"}),
            ),
        )
    campaign = create_campaign(
        database,
        CreateCampaign(dataset_snapshot_id="oracle-test", campaign_group_id="test"),
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
    run_id = batch["run_id"]
    # Eligibility must fail before the worker accesses even a nonexistent oracle path.
    with pytest.raises(Conflict, match="successful simulation"):
        reveal(database, run_id, tmp_path / "absent")
    enqueue_simulation(database, run_id, 0, "scientist", "dispatch", uuid4(), "trace")
    claimed = claim_next(database, tmp_path / "runs")
    assert claimed is not None
    with database.transaction():
        record_receipt(
            database,
            claimed,
            {
                "run_id": str(run_id),
                "protocol_hash": claimed["protocol_hash"],
                "simulator_version": "10.1.0",
                "status": "SIMULATED",
                "source_kind": "synthetic_test",
            },
        )
        transition(database, claimed, "SIMULATED", "test-simulation")
    oracle.write_bytes(records + b"tampered")
    with pytest.raises(Conflict, match="checksum"):
        reveal(database, run_id, tmp_path)
    oracle.write_bytes(records)
    rows = reveal(database, run_id, tmp_path)
    assert len(rows) == 8
    assert {r["candidate_id"] for r in rows} == set(batch["run_spec"]["candidate_ids"])
    assert {r["qc_state"] for r in rows} == ({"QUARANTINED"} if include_records else {"UNOBSERVED"})
    assert all(r["observed_yield_pct"] is None for r in rows)
    assert len(reveal(database, run_id, tmp_path / "absent")) == 8
    assert not list(database.execute("SELECT * FROM training_observations"))
    with pytest.raises(psycopg.errors.RaiseException), database.transaction():
        database.execute("DELETE FROM measurements WHERE run_id=%s", (run_id,))

    run = database.execute("SELECT version FROM experiment_runs WHERE id=%s", (run_id,)).fetchone()
    assert run is not None
    with pytest.raises(RuntimeError), database.transaction():
        analyze(database, run_id, run["version"], "scientist", "rolled-back", uuid4(), "trace")
        raise RuntimeError("failure before commit")
    assert (
        database.execute("SELECT * FROM campaign_analyses WHERE run_id=%s", (run_id,)).fetchone()
        is None
    )
    persisted = database.execute(
        "SELECT status FROM experiment_runs WHERE id=%s", (run_id,)
    ).fetchone()
    assert persisted is not None and persisted["status"] == "QC_COMPLETE"
    schema_row = database.execute("SELECT current_schema() AS name").fetchone()
    assert schema_row is not None
    barrier = Barrier(2)

    def concurrent_analysis(index: int) -> dict[str, object]:
        with connect(os.environ["ATLAS_TEST_DATABASE_URL"]) as independent:
            independent.execute(
                sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_row["name"]))
            )
            barrier.wait(timeout=10)
            return analyze(
                independent,
                run_id,
                run["version"],
                "scientist",
                f"concurrent-{index}",
                uuid4(),
                "trace",
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(concurrent_analysis, range(2)))
    assert results[0]["id"] == results[1]["id"]
    result = analyze(database, run_id, run["version"], "scientist", "analyze", uuid4(), "trace")
    assert result["snapshot"]["observations"] == []
    assert result["snapshot"]["best_observed"] is None
    assert (
        analyze(database, run_id, run["version"], "scientist", "analyze", uuid4(), "trace")["id"]
        == result["id"]
    )
    assert (
        analyze(database, run_id, run["version"], "scientist", "new-analysis", uuid4(), "trace")[
            "id"
        ]
        == result["id"]
    )
    current = database.execute(
        "SELECT version FROM campaigns WHERE id=%s", (campaign.id,)
    ).fetchone()
    assert current is not None
    barrier = Barrier(2)

    def concurrent_proposal(index: int) -> dict[str, object] | None:
        with connect(os.environ["ATLAS_TEST_DATABASE_URL"]) as independent:
            independent.execute(
                sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_row["name"]))
            )
            barrier.wait(timeout=10)
            try:
                return propose_batch(
                    independent,
                    campaign.id,
                    ProposeCommand(
                        expected_version=current["version"],
                        previous_snapshot_hash=result["snapshot_hash"],
                    ),
                    "scientist",
                    f"next-plan-{index}",
                    uuid4(),
                    "trace",
                )
            except Conflict:
                return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        proposals = list(executor.map(concurrent_proposal, range(2)))
    successful = [p for p in proposals if p is not None]
    assert len(successful) == 1
    next_batch = database.execute(
        "SELECT * FROM experiment_batches WHERE id=%s", (successful[0]["id"],)
    ).fetchone()
    assert next_batch is not None
    assert not set(next_batch["run_spec"]["candidate_ids"]) & set(
        batch["run_spec"]["candidate_ids"]
    )
    with pytest.raises(psycopg.errors.RaiseException), database.transaction():
        database.execute("DELETE FROM campaign_analyses WHERE run_id=%s", (run_id,))
