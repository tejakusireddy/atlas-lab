"""Campaign mutations are atomic with idempotency, audit, and outbox records."""

import hashlib
from uuid import UUID, uuid4

from atlas_domain.hashing import content_hash
from psycopg.types.json import Jsonb

from atlas_campaigns.database import Connection
from atlas_campaigns.models import Campaign, CreateCampaign
from atlas_campaigns.telemetry import operation, remember_campaign


class Conflict(ValueError):
    pass


class NotFound(ValueError):
    pass


@operation("campaign.create")
def create_campaign(
    connection: Connection,
    command: CreateCampaign,
    actor: str,
    idempotency_key: str,
    request_id: UUID,
    trace_id: str,
) -> Campaign:
    if not 1 <= len(actor) <= 200 or not 1 <= len(idempotency_key) <= 200:
        raise ValueError("Actor and idempotency key must contain 1–200 characters")
    request_hash = content_hash(command.model_dump(mode="json"))
    # Serialize the same actor/operation/key before the unique reservation exists.
    key = f"{actor}:campaign.create:{idempotency_key}"
    lock = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], signed=True)
    with connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (lock,))
        previous = connection.execute(
            """SELECT request_hash, resource_id FROM mutation_keys
            WHERE actor_id=%s AND operation='campaign.create' AND idempotency_key=%s""",
            (actor, idempotency_key),
        ).fetchone()
        if previous:
            if previous["request_hash"] != request_hash:
                raise Conflict("Idempotency key was used for a different request")
            return get_campaign(connection, previous["resource_id"], actor)
        group = connection.execute(
            """SELECT eligible_count FROM dataset_groups
            WHERE snapshot_id=%s AND group_id=%s""",
            (command.dataset_snapshot_id, command.campaign_group_id),
        ).fetchone()
        if group is None:
            raise NotFound("Dataset snapshot or campaign group is not registered")
        if group["eligible_count"] < command.budget.max_unique_experiments:
            raise Conflict("Candidate pool is smaller than the requested budget")
        campaign_id = uuid4()
        row = connection.execute(
            """INSERT INTO campaigns
            (id,owner_id,snapshot_id,group_id,budget_max,batch_size,seed,acquisition_strategy,predictor)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
            (
                campaign_id,
                actor,
                command.dataset_snapshot_id,
                command.campaign_group_id,
                command.budget.max_unique_experiments,
                command.budget.batch_size,
                command.seed,
                command.acquisition_strategy,
                command.predictor,
            ),
        ).fetchone()
        assert row is not None
        connection.execute(
            """INSERT INTO mutation_keys
            (actor_id,operation,idempotency_key,request_hash,resource_id)
            VALUES (%s,'campaign.create',%s,%s,%s)""",
            (actor, idempotency_key, request_hash, campaign_id),
        )
        connection.execute(
            """INSERT INTO audit_events
            (id,actor_id,resource_id,action,request_id,trace_id,details)
            VALUES (%s,%s,%s,'campaign.create',%s,%s,%s)""",
            (
                uuid4(),
                actor,
                campaign_id,
                request_id,
                trace_id,
                Jsonb({"request_hash": request_hash}),
            ),
        )
        connection.execute(
            """INSERT INTO outbox_events
            (id,aggregate_id,aggregate_version,event_type,payload)
            VALUES (%s,%s,0,'campaign.created',%s)""",
            (uuid4(), campaign_id, Jsonb({"campaign_id": str(campaign_id), "trace_id": trace_id})),
        )
        remember_campaign(connection, campaign_id)
        return Campaign.model_validate(row)


def get_campaign(connection: Connection, campaign_id: UUID, actor: str) -> Campaign:
    row = connection.execute(
        "SELECT * FROM campaigns WHERE id=%s AND owner_id=%s", (campaign_id, actor)
    ).fetchone()
    if row is None:
        raise NotFound("Campaign not found")
    return Campaign.model_validate(row)


def list_campaigns(
    connection: Connection, actor: str, limit: int = 50, offset: int = 0
) -> list[Campaign]:
    if not 1 <= limit <= 100 or offset < 0:
        raise ValueError("Invalid pagination")
    return [
        Campaign.model_validate(row)
        for row in connection.execute(
            "SELECT * FROM campaigns WHERE owner_id=%s "
            "ORDER BY created_at DESC,id LIMIT %s OFFSET %s",
            (actor, limit, offset),
        )
    ]
