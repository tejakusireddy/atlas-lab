CREATE TABLE campaign_analyses (
    id UUID PRIMARY KEY,
    campaign_id UUID NOT NULL REFERENCES campaigns(id),
    run_id UUID NOT NULL UNIQUE REFERENCES experiment_runs(id),
    snapshot_hash TEXT NOT NULL CHECK (snapshot_hash ~ '^sha256:[0-9a-f]{64}$'),
    snapshot JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER campaign_analyses_immutable BEFORE UPDATE OR DELETE ON campaign_analyses
FOR EACH ROW EXECUTE FUNCTION reject_reference_mutation();
