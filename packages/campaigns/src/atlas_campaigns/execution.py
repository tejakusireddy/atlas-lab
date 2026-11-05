"""Durable simulation intent, single-attempt dispatch, and explicit reconciliation."""

import argparse
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from atlas_domain.hashing import content_hash
from atlas_instrument_gateway.compiler import compile_protocol
from atlas_instrument_gateway.simulator import simulate_plan
from atlas_instrument_gateway.spec import RunPlan
from psycopg.types.json import Jsonb

from atlas_campaigns.database import Connection, connect
from atlas_campaigns.service import Conflict, NotFound
from atlas_campaigns.workflow import prior_mutation, record_mutation

TRANSITIONS = {
    "QC_COMPLETE": {"ANALYZED"},
    "SIMULATED": {"MEASUREMENT_PENDING"},
    "MEASUREMENT_PENDING": {"QC_COMPLETE"},
    "APPROVED": {"VALIDATING"},
    "VALIDATING": {"VALIDATED", "FAILED_PRE_DISPATCH"},
    "VALIDATED": {"DISPATCH_PENDING"},
    "DISPATCH_PENDING": {"SIMULATING", "FAILED_PRE_DISPATCH"},
    "SIMULATING": {"SIMULATED", "EXECUTION_FAILED", "EXECUTION_UNKNOWN"},
    "EXECUTION_UNKNOWN": {"SIMULATED", "EXECUTION_FAILED"},
}


def get_run(connection: Connection, run_id: UUID, actor: str, role: str) -> dict[str, Any]:
    row = connection.execute(
        """SELECT r.*,b.campaign_id,b.plan_hash,b.run_spec FROM experiment_runs r
        JOIN experiment_batches b ON b.id=r.batch_id JOIN campaigns c ON c.id=b.campaign_id
        WHERE r.id=%s AND (c.owner_id=%s OR %s='reviewer')""",
        (run_id, actor, role),
    ).fetchone()
    if row is None:
        raise NotFound("Run not found")
    return row


def transition(
    connection: Connection,
    run: dict[str, Any],
    target: str,
    trace_id: str,
    event_type: str | None = None,
) -> dict[str, Any]:
    if target not in TRANSITIONS.get(run["status"], set()):
        raise Conflict(f"Illegal execution transition {run['status']} -> {target}")
    row = connection.execute(
        """UPDATE experiment_runs SET status=%s,version=version+1
        WHERE id=%s AND version=%s RETURNING *""",
        (target, run["id"], run["version"]),
    ).fetchone()
    if row is None:
        raise Conflict("Run version changed")
    connection.execute(
        "UPDATE experiment_batches SET status=%s,version=version+1 WHERE id=%s",
        (target, run["batch_id"]),
    )
    event_type = event_type or "run." + target.lower()
    payload = {"status": target, "trace_id": trace_id}
    connection.execute(
        """INSERT INTO run_events(id,run_id,sequence,event_type,trace_id,payload)
        VALUES (%s,%s,%s,%s,%s,%s)""",
        (uuid4(), run["id"], row["version"] + 1, event_type, trace_id, Jsonb(payload)),
    )
    connection.execute(
        """INSERT INTO outbox_events
        (id,aggregate_id,aggregate_version,event_type,payload) VALUES (%s,%s,%s,%s,%s)""",
        (uuid4(), run["id"], row["version"], event_type, Jsonb(payload)),
    )
    return row


def validate_approval(connection: Connection, run: dict[str, Any], spec: RunPlan) -> None:
    campaign = connection.execute(
        "SELECT status,snapshot_id FROM campaigns WHERE id=%s", (spec.campaign_id,)
    ).fetchone()
    if (
        campaign is None
        or campaign["status"] != "ACTIVE"
        or campaign["snapshot_id"] != spec.source_dataset_snapshot
    ):
        raise Conflict("Campaign does not permit this approved execution")
    approval = connection.execute(
        "SELECT * FROM approvals WHERE id=%s", (run["approval_id"],)
    ).fetchone()
    if (
        approval is None
        or approval["decision"] != "APPROVE"
        or approval["expires_at"] <= datetime.now(UTC)
        or approval["plan_hash"] != spec.plan_hash()
        or approval["batch_id"] != spec.batch_id
        or approval["actor_id"] == spec.created_by
        or spec.run_id != run["id"]
        or spec.batch_id != run["batch_id"]
    ):
        raise Conflict("Missing, expired, or mismatched independent approval")


def enqueue_simulation(
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
        prior = prior_mutation(connection, actor, "run.simulate", key, request_hash)
        if prior:
            return get_run(connection, prior, actor, "scientist")
        visible = get_run(connection, run_id, actor, "scientist")
        run = connection.execute(
            "SELECT * FROM experiment_runs WHERE id=%s FOR UPDATE", (run_id,)
        ).fetchone()
        assert run is not None
        if run["status"] != "APPROVED" or run["version"] != expected_version:
            raise Conflict("Run is not at the expected approved version")
        spec = RunPlan.model_validate(visible["run_spec"])
        validate_approval(connection, run, spec)
        artifact = compile_protocol(spec)
        if artifact.plan_hash != visible["plan_hash"]:
            raise Conflict("Work-order hash mismatch")
        run = transition(connection, run, "VALIDATING", trace_id)
        run = transition(connection, run, "VALIDATED", trace_id)
        connection.execute(
            "UPDATE experiment_runs SET protocol_hash=%s,trace_id=%s WHERE id=%s",
            (artifact.protocol_hash, trace_id, run_id),
        )
        transition(connection, run, "DISPATCH_PENDING", trace_id, "run.dispatch_requested")
        record_mutation(
            connection, actor, "run.simulate", key, request_hash, run_id, request_id, trace_id
        )
        return get_run(connection, run_id, actor, "scientist")


def claim_next(connection: Connection, root: Path) -> dict[str, Any] | None:
    with connection.transaction():
        event = connection.execute("""SELECT * FROM outbox_events WHERE published_at IS NULL
            AND event_type='run.dispatch_requested' ORDER BY created_at,id
            FOR UPDATE SKIP LOCKED LIMIT 1""").fetchone()
        if event is None:
            return None
        run = connection.execute(
            "SELECT * FROM experiment_runs WHERE id=%s FOR UPDATE", (event["aggregate_id"],)
        ).fetchone()
        if run is None:
            raise Conflict("Dispatch event has no run")
        connection.execute(
            "UPDATE outbox_events SET published_at=now() WHERE id=%s", (event["id"],)
        )
        if run["status"] != "DISPATCH_PENDING":
            return None
        batch = connection.execute(
            "SELECT run_spec FROM experiment_batches WHERE id=%s", (run["batch_id"],)
        ).fetchone()
        assert batch is not None
        spec = RunPlan.model_validate(batch["run_spec"])
        try:
            validate_approval(connection, run, spec)
        except Conflict:
            transition(connection, run, "FAILED_PRE_DISPATCH", run["trace_id"])
            return None
        if compile_protocol(spec).protocol_hash != run["protocol_hash"]:
            transition(connection, run, "FAILED_PRE_DISPATCH", run["trace_id"])
            return None
        attempt = uuid4()
        output = root.resolve() / str(run["id"])
        connection.execute(
            """UPDATE experiment_runs
            SET attempt_id=%s,lease_until=%s,artifact_directory=%s WHERE id=%s""",
            (attempt, datetime.now(UTC) + timedelta(minutes=5), str(output), run["id"]),
        )
        claimed = transition(connection, run, "SIMULATING", run["trace_id"])
        return {**claimed, "run_spec": spec.model_dump(mode="json")}


def execute_next(connection: Connection, root: Path) -> dict[str, Any] | None:
    claimed = claim_next(connection, root)
    if claimed is None:
        return None
    try:
        result = simulate_plan(
            RunPlan.model_validate(claimed["run_spec"]), Path(claimed["artifact_directory"])
        )
        status = result["status"]
    except Exception:
        # Any exception after claim is conservative: execution may have occurred.
        status = "EXECUTION_UNKNOWN"
    with connection.transaction():
        run = connection.execute(
            "SELECT * FROM experiment_runs WHERE id=%s FOR UPDATE", (claimed["id"],)
        ).fetchone()
        assert run is not None
        if run["status"] != "SIMULATING" or run["attempt_id"] != claimed["attempt_id"]:
            raise Conflict("Execution ownership changed; explicit reconciliation required")
        return transition(connection, run, status, run["trace_id"])


def recover_expired(connection: Connection) -> int:
    with connection.transaction():
        runs = list(
            connection.execute("""SELECT * FROM experiment_runs WHERE status='SIMULATING'
            AND lease_until < now() FOR UPDATE SKIP LOCKED""")
        )
        for run in runs:
            transition(connection, run, "EXECUTION_UNKNOWN", run["trace_id"])
        return len(runs)


def reconcile(
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
        prior = prior_mutation(connection, actor, "run.reconcile", key, request_hash)
        if prior:
            return get_run(connection, prior, actor, "reviewer")
        run = connection.execute(
            "SELECT * FROM experiment_runs WHERE id=%s FOR UPDATE", (run_id,)
        ).fetchone()
        if run is None:
            raise NotFound("Run not found")
        if run["status"] != "EXECUTION_UNKNOWN" or run["version"] != expected_version:
            raise Conflict("Run is not at the expected unknown version")
        receipt_path = Path(run["artifact_directory"]) / "receipt/receipt.json"
        if not receipt_path.exists():
            raise Conflict("No durable vendor receipt; outcome remains unknown")
        try:
            receipt = json.loads(receipt_path.read_text())
        except (OSError, ValueError) as error:
            raise Conflict("Durable receipt is unreadable; outcome remains unknown") from error
        if not isinstance(receipt, dict):
            raise Conflict("Durable receipt must be an object")
        if (
            receipt.get("run_id") != str(run_id)
            or receipt.get("protocol_hash") != run["protocol_hash"]
            or receipt.get("simulator_version") != "10.1.0"
            or receipt.get("status") not in ("SIMULATED", "EXECUTION_FAILED")
        ):
            raise Conflict("Durable receipt does not match this execution")
        transition(connection, run, receipt["status"], trace_id, "run.reconciled")
        record_mutation(
            connection, actor, "run.reconcile", key, request_hash, run_id, request_id, trace_id
        )
        return get_run(connection, run_id, actor, "reviewer")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, default=Path("artifacts/runs"))
    parser.add_argument("--recover-expired", action="store_true")
    args = parser.parse_args()
    with connect() as connection:
        if args.recover_expired:
            print(json.dumps({"unknown_runs": recover_expired(connection)}))
        else:
            result = execute_next(connection, args.artifacts)
            print(json.dumps(result, default=str))


if __name__ == "__main__":
    main()
