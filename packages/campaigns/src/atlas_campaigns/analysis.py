"""Immutable released-observation snapshots and campaign progress summaries."""

from collections import Counter
from typing import Any
from uuid import UUID, uuid4

from atlas_domain.hashing import content_hash
from atlas_science.decisions import decide
from atlas_science.records import Candidate
from psycopg.types.json import Jsonb

from atlas_campaigns.database import Connection
from atlas_campaigns.execution import get_run, transition
from atlas_campaigns.service import Conflict
from atlas_campaigns.telemetry import local_span, operation
from atlas_campaigns.workflow import prior_mutation, record_mutation


@operation("campaign.analyze")
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
        existing = connection.execute(
            "SELECT * FROM campaign_analyses WHERE run_id=%s", (run_id,)
        ).fetchone()
        if existing:
            record_mutation(
                connection, actor, "run.analyze", key, request_hash, run_id, request_id, trace_id
            )
            return existing
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
        receipt = connection.execute(
            "SELECT * FROM execution_receipts WHERE run_id=%s", (run_id,)
        ).fetchone()
        if receipt is None or content_hash(receipt["receipt"]) != receipt["receipt_hash"]:
            raise Conflict("Verified execution receipt required for analysis")
        batch = connection.execute(
            "SELECT * FROM experiment_batches WHERE id=%s", (run["batch_id"],)
        ).fetchone()
        assert batch is not None
        batch_ids = {str(m["id"]) for m in measurements if m["run_id"] == run_id}
        batch_observations = [m for m in observations if m["measurement_id"] in batch_ids]

        def counts(rows: list[dict[str, Any]]) -> dict[str, int]:
            counter = Counter(m["qc_state"] for m in rows)
            return {state: counter[state] for state in ("PASSED", "QUARANTINED", "UNOBSERVED")}

        best = max(observations, key=lambda m: m["observed_yield_pct"], default=None)
        next_decision = None
        if campaign["acquisition_strategy"] != "random":
            candidates = [
                Candidate.model_validate(row["input_record"])
                for row in connection.execute(
                    "SELECT input_record FROM dataset_candidates "
                    "WHERE snapshot_id=%s AND group_id=%s "
                    "ORDER BY candidate_id",
                    (campaign["snapshot_id"], campaign["group_id"]),
                )
            ]
            selected = [
                row["candidate_id"]
                for row in connection.execute(
                    "SELECT candidate_id FROM campaign_selections "
                    "WHERE campaign_id=%s ORDER BY candidate_id",
                    (campaign["id"],),
                )
            ]
            with local_span("model.update"):
                next_decision, artifact = decide(
                    candidates,
                    selected,
                    {m["candidate_id"]: m["observed_yield_pct"] for m in observations},
                    campaign["acquisition_strategy"],
                    campaign["predictor"],
                    campaign["seed"] + len(selected),
                    min(campaign["batch_size"], campaign["budget_max"] - len(selected)),
                    campaign["budget_max"],
                )
            next_decision["training_measurements"] = observations
            next_decision["external_training"] = None
            if artifact is not None:
                connection.execute(
                    "INSERT INTO model_artifacts(model_hash,artifact,format) "
                    "VALUES (%s,%s,'python-pickle-v5') ON CONFLICT DO NOTHING",
                    (next_decision["model_hash"], artifact),
                )
        snapshot = {
            "schema_version": "1.2",
            "next_decision": next_decision,
            "next_decision_hash": content_hash(next_decision) if next_decision else None,
            "batch_id": str(batch["id"]),
            "batch_number": batch["ordinal"],
            "selected_candidate_ids": visible["run_spec"]["candidate_ids"],
            "approved_work_order_hash": visible["plan_hash"],
            "simulation_receipt_hash": receipt["receipt_hash"],
            "previous_snapshot_hash": batch["previous_snapshot_hash"],
            "selection_context": batch["selection_context"],
            "released_measurement_ids": sorted(batch_ids),
            "released_measurements": [
                {
                    "measurement_id": str(m["id"]),
                    "candidate_id": m["candidate_id"],
                    "qc_state": m["qc_state"],
                }
                for m in measurements
                if m["run_id"] == run_id
            ],
            "batch_qc_counts": counts([m for m in measurements if m["run_id"] == run_id]),
            "batch_best_observed": max(
                batch_observations, key=lambda m: m["observed_yield_pct"], default=None
            ),
            "cumulative_best_observed": best,
            "acquisition_version": next_decision["version"]
            if next_decision
            else "random-without-replacement-v1",
            "campaign_id": str(campaign["id"]),
            "run_id": str(run_id),
            "dataset_snapshot_id": campaign["snapshot_id"],
            "reserved_count": campaign["budget_used"],
            "budget_max": campaign["budget_max"],
            "qc_counts": counts(measurements),
            "observations": observations,
            "best_observed": best,
            "selection_policy": campaign["acquisition_strategy"],
            "model_revision": next_decision["model_hash"] if next_decision else None,
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
