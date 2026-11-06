"""Release checksum-bound historical outcomes after successful approved simulation."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from atlas_campaigns.database import Connection, connect
from atlas_campaigns.execution import transition
from atlas_campaigns.service import Conflict, NotFound
from atlas_campaigns.telemetry import operation
from atlas_instrument_gateway.spec import RunPlan
from atlas_science.records import Observation
from psycopg.types.json import Jsonb
from pydantic import ValidationError


def checked_records(snapshot: Path, manifest_hash: str) -> tuple[dict[str, Any], str, bytes]:
    manifest_bytes = (snapshot / "source_manifest.json").read_bytes()
    if "sha256:" + hashlib.sha256(manifest_bytes).hexdigest() != manifest_hash:
        raise Conflict("Oracle manifest does not match registered snapshot")
    manifest: dict[str, Any] = json.loads(manifest_bytes)
    records = (snapshot / "oracle/observations.jsonl").read_bytes()
    digest = hashlib.sha256(records).hexdigest()
    if digest != manifest["artifact_hashes"]["oracle/observations.jsonl"]:
        raise Conflict("Oracle artifact checksum mismatch")
    if manifest.get("yield_unit") != "percent" or not manifest.get("doi"):
        raise Conflict("Oracle units or source citation missing")
    return manifest, digest, records


def quality(
    raw: dict[str, Any] | None, candidate: dict[str, Any], manifest: dict[str, Any]
) -> tuple[str, float | None, str | None]:
    if raw is None:
        return "UNOBSERVED", None, "No historical record for selected candidate"
    try:
        observation = Observation.model_validate(raw)
    except ValidationError:
        return "QUARANTINED", None, "Invalid observation schema or outcome range"
    if (
        observation.source_record_id != candidate.get("source_record_id")
        or observation.source_file_sha256 != candidate.get("source_file_sha256")
        or observation.source_file_sha256 != manifest["source_file_sha256"]
        or observation.source_kind != "historical_observed"
    ):
        return "QUARANTINED", None, "Unverified historical provenance"
    if observation.qc_state != "PASSED" or observation.observed_yield_pct is None:
        return (
            observation.qc_state if observation.qc_state != "PASSED" else "UNOBSERVED",
            None,
            (observation.reason or "No valid historical outcome"),
        )
    try:
        raw_yield = float(observation.raw_yield)
    except ValueError:
        return "QUARANTINED", None, "Raw yield is not numeric"
    if raw_yield != observation.observed_yield_pct:
        return "QUARANTINED", None, "Raw and normalized outcomes differ"
    return "PASSED", observation.observed_yield_pct, None


@operation("oracle.reveal")
def reveal(connection: Connection, run_id: UUID, snapshot: Path) -> list[dict[str, Any]]:
    with connection.transaction():
        run = connection.execute(
            "SELECT * FROM experiment_runs WHERE id=%s FOR UPDATE", (run_id,)
        ).fetchone()
        if run is None:
            raise NotFound("Run not found")
        if run["status"] in ("QC_COMPLETE", "ANALYZED"):
            return list(connection.execute("SELECT * FROM measurements WHERE run_id=%s", (run_id,)))
        if run["status"] != "SIMULATED":
            raise Conflict("Historical release requires successful simulation")
        batch = connection.execute(
            "SELECT * FROM experiment_batches WHERE id=%s", (run["batch_id"],)
        ).fetchone()
        assert batch is not None
        spec = RunPlan.model_validate(batch["run_spec"])
        campaign = connection.execute(
            "SELECT * FROM campaigns WHERE id=%s FOR UPDATE", (batch["campaign_id"],)
        ).fetchone()
        assert campaign is not None
        if campaign["status"] != "ACTIVE":
            raise Conflict("Campaign is not active")
        selected = list(
            connection.execute(
                """SELECT s.candidate_id,d.input_record FROM campaign_selections s
            JOIN dataset_candidates d ON d.snapshot_id=s.snapshot_id
                AND d.candidate_id=s.candidate_id
            WHERE s.batch_id=%s AND s.campaign_id=%s AND s.snapshot_id=%s""",
                (batch["id"], campaign["id"], spec.source_dataset_snapshot),
            )
        )
        allowed = {row["candidate_id"]: row["input_record"] for row in selected}
        if set(allowed) != set(spec.candidate_ids) or spec.plan_hash() != batch["plan_hash"]:
            raise Conflict("Reserved selections do not match the simulated work order")
        registry = connection.execute(
            "SELECT manifest_hash FROM dataset_snapshots WHERE id=%s", (campaign["snapshot_id"],)
        ).fetchone()
        assert registry is not None
        # Hidden outcomes are opened only after database eligibility checks.
        manifest, digest, records = checked_records(snapshot, registry["manifest_hash"])
        matched: dict[str, dict[str, Any]] = {}
        for line in records.splitlines():
            raw = json.loads(line)
            if not isinstance(raw, dict):
                raise Conflict("Malformed oracle record")
            candidate_id = raw.get("candidate_id")
            if isinstance(candidate_id, str) and candidate_id in allowed:
                if candidate_id in matched:
                    raise Conflict("Duplicate selected oracle record")
                matched[candidate_id] = raw
        run = transition(connection, run, "MEASUREMENT_PENDING", run["trace_id"], "oracle.reveal")
        for candidate_id, candidate in allowed.items():
            raw = matched.get(candidate_id)
            state, value, reason = quality(raw, candidate, manifest)
            source = raw or {}
            kind = source.get("source_kind")
            if kind not in ("historical_observed", "synthetic_test"):
                kind = "missing"
            connection.execute(
                """INSERT INTO measurements(id,run_id,campaign_id,candidate_id,snapshot_id,
                manifest_hash,oracle_hash,source_record_id,source_file_sha256,source_citation,
                source_kind,measurement_mode,units,observed_yield_pct,qc_state,reason,raw_record)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                'historical_replay','percent',%s,%s,%s,%s)""",
                (
                    uuid4(),
                    run_id,
                    campaign["id"],
                    candidate_id,
                    campaign["snapshot_id"],
                    registry["manifest_hash"],
                    digest,
                    source.get("source_record_id"),
                    source.get("source_file_sha256"),
                    "https://doi.org/" + manifest["doi"],
                    kind,
                    value,
                    state,
                    reason,
                    Jsonb(raw),
                ),
            )
        transition(connection, run, "QC_COMPLETE", run["trace_id"], "measurement.qc")
        connection.execute(
            """INSERT INTO audit_events(id,actor_id,resource_id,action,request_id,trace_id,details)
            VALUES (%s,'historical-oracle',%s,'oracle.reveal',%s,%s,%s)""",
            (
                uuid4(),
                run_id,
                uuid4(),
                run["trace_id"],
                Jsonb(
                    {
                        "manifest_hash": registry["manifest_hash"],
                        "oracle_hash": digest,
                        "selected_count": len(allowed),
                    }
                ),
            ),
        )
        return list(connection.execute("SELECT * FROM measurements WHERE run_id=%s", (run_id,)))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_id", type=UUID)
    parser.add_argument("--snapshot", required=True, type=Path)
    args = parser.parse_args()
    with connect() as connection:
        rows = reveal(connection, args.run_id, args.snapshot)
    print(json.dumps({"run_id": str(args.run_id), "released": len(rows)}))


if __name__ == "__main__":
    main()
