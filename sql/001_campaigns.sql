CREATE TABLE dataset_snapshots (
    id TEXT PRIMARY KEY,
    manifest_hash TEXT NOT NULL CHECK (manifest_hash ~ '^sha256:[0-9a-f]{64}$'),
    registered_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE dataset_groups (
    snapshot_id TEXT NOT NULL REFERENCES dataset_snapshots(id),
    group_id TEXT NOT NULL,
    eligible_count INTEGER NOT NULL CHECK (eligible_count > 0),
    PRIMARY KEY (snapshot_id, group_id)
);
CREATE TABLE campaigns (
    id UUID PRIMARY KEY,
    owner_id TEXT NOT NULL CHECK (length(owner_id) BETWEEN 1 AND 200),
    snapshot_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    budget_max INTEGER NOT NULL CHECK (budget_max BETWEEN 1 AND 48),
    batch_size INTEGER NOT NULL CHECK (batch_size BETWEEN 1 AND 8),
    budget_used INTEGER NOT NULL DEFAULT 0 CHECK (budget_used BETWEEN 0 AND budget_max),
    seed BIGINT NOT NULL CHECK (seed BETWEEN 0 AND 2147483647),
    status TEXT NOT NULL DEFAULT 'DRAFT' CHECK (status IN
        ('DRAFT','READY','ACTIVE','PAUSED','COMPLETE','FAILED','CANCELLED')),
    version BIGINT NOT NULL DEFAULT 0 CHECK (version >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    FOREIGN KEY (snapshot_id, group_id) REFERENCES dataset_groups(snapshot_id, group_id),
    CHECK (batch_size <= budget_max)
);
CREATE INDEX campaigns_owner_created ON campaigns(owner_id, created_at, id);
CREATE TABLE mutation_keys (
    actor_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 200),
    request_hash TEXT NOT NULL,
    resource_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(actor_id, operation, idempotency_key)
);
CREATE TABLE audit_events (
    id UUID PRIMARY KEY,
    actor_id TEXT NOT NULL,
    resource_id UUID NOT NULL,
    action TEXT NOT NULL,
    request_id UUID NOT NULL,
    trace_id TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    details JSONB NOT NULL
);
CREATE FUNCTION reject_audit_mutation() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'audit_events are append-only';
END;
$$;
CREATE TRIGGER audit_events_immutable BEFORE UPDATE OR DELETE ON audit_events
FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();
CREATE TABLE outbox_events (
    id UUID PRIMARY KEY,
    aggregate_id UUID NOT NULL,
    aggregate_version BIGINT NOT NULL,
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at TIMESTAMPTZ,
    UNIQUE(aggregate_id, aggregate_version)
);
CREATE INDEX outbox_pending ON outbox_events(created_at) WHERE published_at IS NULL;
