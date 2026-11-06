CREATE TABLE reconciliation_requests (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES experiment_runs(id),
    expected_version BIGINT NOT NULL CHECK (expected_version >= 0),
    actor_id TEXT NOT NULL,
    request_id UUID NOT NULL,
    trace_id TEXT NOT NULL,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER reconciliation_requests_immutable BEFORE UPDATE OR DELETE ON reconciliation_requests
FOR EACH ROW EXECUTE FUNCTION reject_reference_mutation();
CREATE TABLE reconciliation_results (
    request_id UUID PRIMARY KEY REFERENCES reconciliation_requests(id),
    status TEXT NOT NULL CHECK (status IN ('SUCCEEDED','FAILED')),
    reason TEXT CHECK (reason IN ('receipt_unavailable_or_invalid','stale_request')),
    completed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((status='SUCCEEDED' AND reason IS NULL) OR (status='FAILED' AND reason IS NOT NULL))
);
CREATE TRIGGER reconciliation_results_immutable BEFORE UPDATE OR DELETE ON reconciliation_results
FOR EACH ROW EXECUTE FUNCTION reject_reference_mutation();
