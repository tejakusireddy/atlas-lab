"""Version-checked proposal and independent approval of immutable work orders."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from atlas_domain.hashing import content_hash
from atlas_instrument_gateway.spec import RunPlan, Transfer
from atlas_optimization.selection import eligible_ids, random_batch
from psycopg.types.json import Jsonb
from pydantic import Field

from atlas_campaigns.database import Connection
from atlas_campaigns.models import Contract
from atlas_campaigns.service import Conflict, NotFound
from atlas_campaigns.telemetry import operation


class Forbidden(PermissionError):
    pass


class VersionCommand(Contract):
    expected_version: int = Field(ge=0, strict=True)


class ProposeCommand(VersionCommand):
    previous_snapshot_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")


class DecisionCommand(Contract):
    expected_version: int = Field(ge=0, strict=True)
    plan_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


def prior_mutation(
    connection: Connection, actor: str, operation: str, key: str, request_hash: str
) -> UUID | None:
    if not 1 <= len(key) <= 200:
        raise ValueError("Invalid idempotency key")
    lock = int.from_bytes(
        hashlib.sha256(f"{actor}:{operation}:{key}".encode()).digest()[:8], signed=True
    )
    connection.execute("SELECT pg_advisory_xact_lock(%s)", (lock,))
    previous = connection.execute(
        """SELECT resource_id,request_hash FROM mutation_keys
        WHERE actor_id=%s AND operation=%s AND idempotency_key=%s""",
        (actor, operation, key),
    ).fetchone()
    if previous:
        if previous["request_hash"] != request_hash:
            raise Conflict("Idempotency key was used for a different request")
        return UUID(str(previous["resource_id"]))
    return None


def record_mutation(
    connection: Connection,
    actor: str,
    operation: str,
    key: str,
    request_hash: str,
    resource_id: UUID,
    request_id: UUID,
    trace_id: str,
) -> None:
    connection.execute(
        """INSERT INTO mutation_keys
        (actor_id,operation,idempotency_key,request_hash,resource_id) VALUES (%s,%s,%s,%s,%s)""",
        (actor, operation, key, request_hash, resource_id),
    )
    connection.execute(
        """INSERT INTO audit_events
        (id,actor_id,resource_id,action,request_id,trace_id,details)
        VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (
            uuid4(),
            actor,
            resource_id,
            operation,
            request_id,
            trace_id,
            Jsonb({"request_hash": request_hash}),
        ),
    )


def get_batch(
    connection: Connection, campaign_id: UUID, batch_id: UUID, actor: str, role: str
) -> dict[str, Any]:
    row = connection.execute(
        """SELECT b.* FROM experiment_batches b JOIN campaigns c
        ON c.id=b.campaign_id WHERE b.id=%s AND b.campaign_id=%s
        AND (c.owner_id=%s OR %s='reviewer')""",
        (batch_id, campaign_id, actor, role),
    ).fetchone()
    if row is None:
        raise NotFound("Batch not found")
    return row


@operation("batch.propose")
def propose_batch(
    connection: Connection,
    campaign_id: UUID,
    command: ProposeCommand,
    actor: str,
    key: str,
    request_id: UUID,
    trace_id: str,
) -> dict[str, Any]:
    request_hash = content_hash(
        {"campaign_id": str(campaign_id), **command.model_dump(mode="json")}
    )
    with connection.transaction():
        prior = prior_mutation(connection, actor, "batch.propose", key, request_hash)
        if prior:
            return get_batch(connection, campaign_id, prior, actor, "scientist")
        campaign = connection.execute(
            "SELECT * FROM campaigns WHERE id=%s AND owner_id=%s FOR UPDATE", (campaign_id, actor)
        ).fetchone()
        if campaign is None:
            raise NotFound("Campaign not found")
        if campaign["version"] != command.expected_version:
            raise Conflict("Campaign version changed")
        if campaign["status"] not in ("DRAFT", "READY", "ACTIVE"):
            raise Conflict("Campaign does not permit planning")
        latest = connection.execute(
            """SELECT status,ordinal FROM experiment_batches
            WHERE campaign_id=%s ORDER BY ordinal DESC LIMIT 1""",
            (campaign_id,),
        ).fetchone()
        if latest and latest["status"] not in ("REJECTED", "ANALYZED"):
            raise Conflict("Previous batch must be rejected or analyzed before replanning")
        previous = connection.execute(
            "SELECT snapshot_hash,snapshot FROM campaign_analyses "
            "WHERE campaign_id=%s ORDER BY created_at DESC,id DESC LIMIT 1",
            (campaign_id,),
        ).fetchone()
        previous_hash = previous["snapshot_hash"] if previous else None
        if previous and content_hash(previous["snapshot"]) != previous_hash:
            raise Conflict("Previous analysis snapshot integrity failure")
        if command.previous_snapshot_hash != previous_hash:
            raise Conflict("Proposal must reference the latest committed analysis snapshot")
        pool = [
            row["candidate_id"]
            for row in connection.execute(
                """SELECT candidate_id
            FROM dataset_candidates WHERE snapshot_id=%s AND group_id=%s ORDER BY candidate_id""",
                (campaign["snapshot_id"], campaign["group_id"]),
            )
        ]
        selected = [
            row["candidate_id"]
            for row in connection.execute(
                "SELECT candidate_id FROM campaign_selections WHERE campaign_id=%s", (campaign_id,)
            )
        ]
        count = min(campaign["batch_size"], campaign["budget_max"] - len(selected))
        if count < 1:
            raise Conflict("Campaign budget exhausted")
        try:
            candidate_ids = random_batch(
                pool, selected, campaign["budget_max"], count, campaign["seed"] + len(selected)
            )
        except ValueError as error:
            raise Conflict(str(error)) from error
        selection_context = {
            "policy": "seeded_random",
            "acquisition_version": "random-without-replacement-v1",
            "model_revision": None,
            "seed": campaign["seed"] + len(selected),
            "candidate_pool_hash": content_hash(pool),
            "excluded_candidate_ids": sorted(selected),
            "previous_snapshot_hash": previous_hash,
        }
        if selected and campaign["acquisition_strategy"] != "random":
            if previous is None or not previous["snapshot"].get("next_decision"):
                raise Conflict("Committed acquisition decision required")
            decision = previous["snapshot"]["next_decision"]
            if content_hash(decision) != previous["snapshot"]["next_decision_hash"]:
                raise Conflict("Acquisition decision integrity failure")
            candidate_ids = decision["selected_ids"]
            eligible = eligible_ids(pool, selected, campaign["budget_max"], count)
            if (
                len(candidate_ids) != count
                or len(set(candidate_ids)) != count
                or not set(candidate_ids).issubset(eligible)
            ):
                raise Conflict("Committed acquisition violates eligibility")
            selection_context = {
                **decision,
                "previous_snapshot_hash": previous_hash,
                "decision_hash": previous["snapshot"]["next_decision_hash"],
            }
        else:
            selection_context["configured_strategy"] = campaign["acquisition_strategy"]
            selection_context["reason"] = (
                "shared_initial_design" if not selected else "random_reference"
            )
        batch_id, run_id = uuid4(), uuid4()
        ordinal = latest["ordinal"] + 1 if latest else 1
        spec = RunPlan(
            campaign_id=campaign_id,
            batch_id=batch_id,
            run_id=run_id,
            source_dataset_snapshot=campaign["snapshot_id"],
            created_by=actor,
            candidate_ids=tuple(candidate_ids),
            transfers=tuple(
                Transfer(candidate_id=candidate_id, destination_well=f"{row}1")
                for row, candidate_id in zip("ABCDEFGH", candidate_ids, strict=False)
            ),
        )
        connection.execute(
            """INSERT INTO experiment_batches
            (id,campaign_id,ordinal,run_id,plan_hash,run_spec,status,created_by,
             previous_snapshot_hash,selection_context)
            VALUES (%s,%s,%s,%s,%s,%s,'AWAITING_APPROVAL',%s,%s,%s)""",
            (
                batch_id,
                campaign_id,
                ordinal,
                run_id,
                spec.plan_hash(),
                Jsonb(spec.model_dump(mode="json")),
                actor,
                previous_hash,
                Jsonb(selection_context),
            ),
        )
        connection.execute(
            """UPDATE campaigns SET status=CASE WHEN status='DRAFT' THEN 'READY'
            ELSE status END,version=version+1 WHERE id=%s""",
            (campaign_id,),
        )
        connection.execute(
            """INSERT INTO outbox_events
            (id,aggregate_id,aggregate_version,event_type,payload)
            VALUES (%s,%s,0,'batch.proposed',%s)""",
            (
                uuid4(),
                batch_id,
                Jsonb(
                    {"batch_id": str(batch_id), "plan_hash": spec.plan_hash(), "trace_id": trace_id}
                ),
            ),
        )
        record_mutation(
            connection, actor, "batch.propose", key, request_hash, batch_id, request_id, trace_id
        )
        return get_batch(connection, campaign_id, batch_id, actor, "scientist")


@operation("batch.decision")
def decide_batch(
    connection: Connection,
    campaign_id: UUID,
    batch_id: UUID,
    command: DecisionCommand,
    decision: Literal["APPROVE", "REJECT"],
    actor: str,
    role: str,
    key: str,
    request_id: UUID,
    trace_id: str,
) -> dict[str, Any]:
    if role != "reviewer":
        raise Forbidden("Reviewer role required")
    operation = "batch." + decision.lower()
    request_hash = content_hash(
        {
            "campaign_id": str(campaign_id),
            "batch_id": str(batch_id),
            **command.model_dump(mode="json"),
        }
    )
    with connection.transaction():
        prior = prior_mutation(connection, actor, operation, key, request_hash)
        if prior:
            return get_batch(connection, campaign_id, prior, actor, role)
        campaign = connection.execute(
            "SELECT * FROM campaigns WHERE id=%s FOR UPDATE", (campaign_id,)
        ).fetchone()
        if campaign is None:
            raise NotFound("Campaign not found")
        batch = connection.execute(
            """SELECT * FROM experiment_batches
            WHERE id=%s AND campaign_id=%s FOR UPDATE""",
            (batch_id, campaign_id),
        ).fetchone()
        if batch is None:
            raise NotFound("Batch not found")
        if actor == batch["created_by"]:
            raise Forbidden("Approval requires a different actor from the proposer")
        if campaign["status"] not in ("READY", "ACTIVE"):
            raise Conflict("Campaign does not permit approval")
        if batch["version"] != command.expected_version or batch["status"] != "AWAITING_APPROVAL":
            raise Conflict("Batch version or status changed")
        spec = RunPlan.model_validate(batch["run_spec"])
        if spec.plan_hash() != command.plan_hash or spec.plan_hash() != batch["plan_hash"]:
            raise Conflict("Approval does not match the immutable work order")
        approval_id = uuid4()
        connection.execute(
            """INSERT INTO approvals
            (id,batch_id,actor_id,plan_hash,decision,policy_version,expires_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (
                approval_id,
                batch_id,
                actor,
                spec.plan_hash(),
                decision,
                spec.policy_version,
                datetime.now(UTC) + timedelta(hours=1),
            ),
        )
        if decision == "APPROVE":
            if campaign["budget_used"] + len(spec.candidate_ids) > campaign["budget_max"]:
                raise Conflict("Approval exceeds remaining budget")
            for candidate_id in spec.candidate_ids:
                connection.execute(
                    """INSERT INTO campaign_selections
                    (campaign_id,candidate_id,snapshot_id,batch_id) VALUES (%s,%s,%s,%s)""",
                    (campaign_id, candidate_id, campaign["snapshot_id"], batch_id),
                )
            connection.execute(
                """UPDATE campaigns SET status='ACTIVE',version=version+1,
                budget_used=budget_used+%s WHERE id=%s""",
                (len(spec.candidate_ids), campaign_id),
            )
            connection.execute(
                "INSERT INTO experiment_runs(id,batch_id,approval_id) VALUES (%s,%s,%s)",
                (spec.run_id, batch_id, approval_id),
            )
            connection.execute(
                """INSERT INTO run_events
                (id,run_id,sequence,event_type,trace_id,payload)
                VALUES (%s,%s,1,'run.approved',%s,%s)""",
                (uuid4(), spec.run_id, trace_id, Jsonb({"plan_hash": spec.plan_hash()})),
            )
        status = "APPROVED" if decision == "APPROVE" else "REJECTED"
        connection.execute(
            "UPDATE experiment_batches SET status=%s,version=version+1 WHERE id=%s",
            (status, batch_id),
        )
        connection.execute(
            """INSERT INTO outbox_events
            (id,aggregate_id,aggregate_version,event_type,payload) VALUES (%s,%s,1,%s,%s)""",
            (uuid4(), batch_id, "batch." + status.lower(), Jsonb({"plan_hash": spec.plan_hash()})),
        )
        record_mutation(
            connection, actor, operation, key, request_hash, batch_id, request_id, trace_id
        )
        return get_batch(connection, campaign_id, batch_id, actor, role)
