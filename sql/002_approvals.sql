CREATE TABLE dataset_candidates (
    snapshot_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    group_id TEXT NOT NULL,
    reaction_key TEXT NOT NULL,
    input_record JSONB NOT NULL,
    PRIMARY KEY(snapshot_id, candidate_id),
    UNIQUE(snapshot_id, reaction_key),
    FOREIGN KEY(snapshot_id, group_id) REFERENCES dataset_groups(snapshot_id, group_id)
);
CREATE TABLE experiment_batches (
    id UUID PRIMARY KEY,
    campaign_id UUID NOT NULL REFERENCES campaigns(id),
    ordinal INTEGER NOT NULL CHECK (ordinal >= 1),
    run_id UUID NOT NULL UNIQUE,
    plan_hash TEXT NOT NULL CHECK (plan_hash ~ '^sha256:[0-9a-f]{64}$'),
    run_spec JSONB NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('AWAITING_APPROVAL','APPROVED','REJECTED',
        'VALIDATING','VALIDATED','DISPATCH_PENDING','SIMULATING','SIMULATED',
        'MEASUREMENT_PENDING','QC_COMPLETE','ANALYZED','EXECUTION_UNKNOWN',
        'EXECUTION_FAILED','FAILED_PRE_DISPATCH','QC_QUARANTINED')),
    version BIGINT NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(campaign_id, ordinal),
    UNIQUE(id, campaign_id)
);
CREATE TABLE approvals (
    id UUID PRIMARY KEY,
    batch_id UUID NOT NULL UNIQUE REFERENCES experiment_batches(id),
    actor_id TEXT NOT NULL,
    plan_hash TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('APPROVE','REJECT')),
    policy_version TEXT NOT NULL,
    decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ NOT NULL,
    CHECK(expires_at > decided_at)
);
CREATE TRIGGER approvals_immutable BEFORE UPDATE OR DELETE ON approvals
FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();
CREATE TABLE campaign_selections (
    campaign_id UUID NOT NULL,
    candidate_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    batch_id UUID NOT NULL,
    PRIMARY KEY(campaign_id, candidate_id),
    FOREIGN KEY(batch_id, campaign_id) REFERENCES experiment_batches(id, campaign_id),
    FOREIGN KEY(snapshot_id, candidate_id) REFERENCES dataset_candidates(snapshot_id, candidate_id)
);
CREATE TABLE experiment_runs (
    id UUID PRIMARY KEY REFERENCES experiment_batches(run_id),
    batch_id UUID NOT NULL UNIQUE REFERENCES experiment_batches(id),
    approval_id UUID NOT NULL UNIQUE REFERENCES approvals(id),
    status TEXT NOT NULL DEFAULT 'APPROVED',
    version BIGINT NOT NULL DEFAULT 0,
    protocol_hash TEXT,
    artifact_directory TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE run_events (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES experiment_runs(id),
    sequence BIGINT NOT NULL CHECK (sequence >= 1),
    event_type TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(run_id, sequence)
);
CREATE TRIGGER run_events_immutable BEFORE UPDATE OR DELETE ON run_events
FOR EACH ROW EXECUTE FUNCTION reject_audit_mutation();
CREATE FUNCTION protect_batch_payload() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.run_spec IS DISTINCT FROM OLD.run_spec OR NEW.plan_hash <> OLD.plan_hash
        OR NEW.run_id <> OLD.run_id OR NEW.campaign_id <> OLD.campaign_id
        OR NEW.created_by <> OLD.created_by OR NEW.ordinal <> OLD.ordinal THEN
        RAISE EXCEPTION 'Work-order payload is immutable; create a new revision';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER batch_payload_immutable BEFORE UPDATE ON experiment_batches
FOR EACH ROW EXECUTE FUNCTION protect_batch_payload();
ALTER TABLE campaigns ADD CONSTRAINT campaign_snapshot_identity UNIQUE(id, snapshot_id);
ALTER TABLE campaign_selections ADD CONSTRAINT selection_campaign_snapshot
FOREIGN KEY(campaign_id, snapshot_id) REFERENCES campaigns(id, snapshot_id);
CREATE FUNCTION reject_reference_mutation() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Registered reference records are immutable';
END;
$$;
CREATE TRIGGER dataset_candidates_immutable BEFORE UPDATE OR DELETE ON dataset_candidates
FOR EACH ROW EXECUTE FUNCTION reject_reference_mutation();
CREATE TRIGGER dataset_groups_immutable BEFORE UPDATE OR DELETE ON dataset_groups
FOR EACH ROW EXECUTE FUNCTION reject_reference_mutation();
CREATE TRIGGER dataset_snapshots_immutable BEFORE UPDATE OR DELETE ON dataset_snapshots
FOR EACH ROW EXECUTE FUNCTION reject_reference_mutation();
