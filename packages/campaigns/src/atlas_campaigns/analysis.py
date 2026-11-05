"""Immutable released-observation snapshots and campaign progress summaries."""

from collections import Counter
from typing import Any
from uuid import UUID, uuid4

from atlas_domain.hashing import content_hash
from psycopg.types.json import Jsonb

from atlas_campaigns.database import Connection
from atlas_campaigns.execution import get_run, transition
from atlas_campaigns.service import Conflict
from atlas_campaigns.workflow import prior_mutation, record_mutation


def analyze(
    connection: Connection,
    run_id: UUID,
    expected_version: int,
    actor: str,
    key: str,
    request_id: UUID,
    trace_id: str,
) -> dict[str, Any]:
    request_hash = content_hash({"run_id": str(run_id), "expected_version": expected_version})
    with connection.transaction():
        prior = prior_mutation(connection, actor, "run.analyze", key, request_hash)
        visible = get_run(connection, run_id, actor, "scientist")
        if prior:
            row = connection.execute(
                "SELECT * FROM campaign_analyses WHERE run_id=%s", (prior,)
            ).fetchone()
            assert row is not None
            return row
        run = connection.execute(
            "SELECT * FROM experiment_runs WHERE id=%s FOR UPDATE", (run_id,)
        ).fetchone()
        assert run is not None
        if run["status"] != "QC_COMPLETE" or run["version"] != expected_version:
            raise Conflict("Run is not at the expected QC-complete version")
        campaign = connection.execute(
            "SELECT * FROM campaigns WHERE id=%s FOR UPDATE", (visible["campaign_id"],)
        ).fetchone()
        assert campaign is not None
        if campaign["status"] != "ACTIVE":
            raise Conflict("Campaign is not active")
        measurements = list(
            connection.execute(
                """SELECT id,candidate_id,run_id,qc_state,source_kind,observed_yield_pct,
            manifest_hash,oracle_hash FROM measurements
            WHERE campaign_id=%s ORDER BY candidate_id""",
                (campaign["id"],),
            )
        )
        current = {m["candidate_id"] for m in measurements if m["run_id"] == run_id}
        if current != set(visible["run_spec"]["candidate_ids"]):
            raise Conflict("Measurement ledger does not cover this batch")
        observations = [
            {
                "measurement_id": str(m["id"]),
                "candidate_id": m["candidate_id"],
                "observed_yield_pct": m["observed_yield_pct"],
                "manifest_hash": m["manifest_hash"],
                "oracle_hash": m["oracle_hash"],
            }
            for m in measurements
            if m["qc_state"] == "PASSED" and m["source_kind"] == "historical_observed"
        ]
        best = max(observations, key=lambda m: m["observed_yield_pct"], default=None)
        snapshot = {
            "schema_version": "1.0",
            "campaign_id": str(campaign["id"]),
            "run_id": str(run_id),
            "dataset_snapshot_id": campaign["snapshot_id"],
            "reserved_count": campaign["budget_used"],
            "budget_max": campaign["budget_max"],
            "qc_counts": dict(Counter(m["qc_state"] for m in measurements)),
            "observations": observations,
            "best_observed": best,
            "selection_policy": "seeded_random",
            "model_revision": None,
        }
        result = connection.execute(
            """INSERT INTO campaign_analyses(id,campaign_id,run_id,snapshot_hash,snapshot)
            VALUES (%s,%s,%s,%s,%s) RETURNING *""",
            (uuid4(), campaign["id"], run_id, content_hash(snapshot), Jsonb(snapshot)),
        ).fetchone()
        assert result is not None
        transition(connection, run, "ANALYZED", trace_id, "run.analyzed")
        status = "COMPLETE" if campaign["budget_used"] == campaign["budget_max"] else "ACTIVE"
        updated = connection.execute(
            "UPDATE campaigns SET status=%s,version=version+1 WHERE id=%s RETURNING version",
            (status, campaign["id"]),
        ).fetchone()
        assert updated is not None
        connection.execute(
            """INSERT INTO outbox_events(id,aggregate_id,aggregate_version,event_type,payload)
            VALUES (%s,%s,%s,'campaign.analyzed',%s)""",
            (
                uuid4(),
                campaign["id"],
                updated["version"],
                Jsonb(
                    {
                        "analysis_id": str(result["id"]),
                        "snapshot_hash": result["snapshot_hash"],
                        "status": status,
                        "trace_id": trace_id,
                    }
                ),
            ),
        )
        record_mutation(
            connection, actor, "run.analyze", key, request_hash, run_id, request_id, trace_id
        )
        return result
