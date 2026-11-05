ALTER TABLE experiment_runs ADD COLUMN attempt_id UUID;
ALTER TABLE experiment_runs ADD COLUMN lease_until TIMESTAMPTZ;
ALTER TABLE experiment_runs ADD COLUMN trace_id TEXT;
ALTER TABLE experiment_runs ADD CONSTRAINT run_status_valid CHECK (status IN
    ('APPROVED','VALIDATING','VALIDATED','DISPATCH_PENDING','SIMULATING','SIMULATED',
     'EXECUTION_UNKNOWN','EXECUTION_FAILED','FAILED_PRE_DISPATCH'));
CREATE INDEX runs_expired_lease ON experiment_runs(lease_until) WHERE status='SIMULATING';
CREATE FUNCTION protect_run_identity() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.id <> OLD.id OR NEW.batch_id <> OLD.batch_id OR NEW.approval_id <> OLD.approval_id
        OR (OLD.protocol_hash IS NOT NULL AND NEW.protocol_hash IS DISTINCT FROM OLD.protocol_hash)
        OR (OLD.attempt_id IS NOT NULL AND NEW.attempt_id IS DISTINCT FROM OLD.attempt_id)
        OR (OLD.artifact_directory IS NOT NULL AND
            NEW.artifact_directory IS DISTINCT FROM OLD.artifact_directory) THEN
        RAISE EXCEPTION 'Execution identity is immutable';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER run_identity_immutable BEFORE UPDATE ON experiment_runs
FOR EACH ROW EXECUTE FUNCTION protect_run_identity();
