ALTER TABLE experiment_runs DROP CONSTRAINT run_status_valid;
ALTER TABLE experiment_runs ADD CONSTRAINT run_status_valid CHECK (status IN
    ('APPROVED','VALIDATING','VALIDATED','DISPATCH_PENDING','SIMULATING','SIMULATED',
     'EXECUTION_UNKNOWN','EXECUTION_FAILED','FAILED_PRE_DISPATCH','MEASUREMENT_PENDING',
     'QC_COMPLETE','ANALYZED'));
CREATE TABLE measurements (
    id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES experiment_runs(id),
    campaign_id UUID NOT NULL,
    candidate_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    oracle_hash TEXT NOT NULL,
    source_record_id TEXT,
    source_file_sha256 TEXT,
    source_citation TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('historical_observed','synthetic_test','missing')),
    measurement_mode TEXT NOT NULL CHECK (measurement_mode='historical_replay'),
    units TEXT NOT NULL CHECK (units='percent'),
    observed_yield_pct DOUBLE PRECISION,
    qc_state TEXT NOT NULL CHECK (qc_state IN ('PASSED','QUARANTINED','UNOBSERVED')),
    reason TEXT,
    raw_record JSONB,
    revealed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(campaign_id,candidate_id),
    FOREIGN KEY(campaign_id,candidate_id) REFERENCES campaign_selections(campaign_id,candidate_id),
    FOREIGN KEY(snapshot_id,candidate_id) REFERENCES dataset_candidates(snapshot_id,candidate_id),
    CHECK ((qc_state='PASSED' AND source_kind='historical_observed'
        AND observed_yield_pct BETWEEN 0 AND 100 AND observed_yield_pct IS NOT NULL
        AND source_record_id IS NOT NULL AND source_file_sha256 IS NOT NULL)
        OR (qc_state<>'PASSED' AND observed_yield_pct IS NULL))
);
CREATE TRIGGER measurements_immutable BEFORE UPDATE OR DELETE ON measurements
FOR EACH ROW EXECUTE FUNCTION reject_reference_mutation();
CREATE VIEW training_observations AS SELECT * FROM measurements
WHERE qc_state='PASSED' AND source_kind='historical_observed';
