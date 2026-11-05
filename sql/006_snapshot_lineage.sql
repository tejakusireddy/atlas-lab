CREATE TABLE execution_receipts (
    run_id UUID PRIMARY KEY REFERENCES experiment_runs(id),
    receipt_hash TEXT NOT NULL CHECK (receipt_hash ~ '^sha256:[0-9a-f]{64}$'),
    receipt JSONB NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER execution_receipts_immutable BEFORE UPDATE OR DELETE ON execution_receipts
FOR EACH ROW EXECUTE FUNCTION reject_reference_mutation();
ALTER TABLE experiment_batches ADD COLUMN previous_snapshot_hash TEXT;
ALTER TABLE experiment_batches ADD COLUMN selection_context JSONB;
CREATE FUNCTION protect_selection_lineage() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.previous_snapshot_hash IS DISTINCT FROM OLD.previous_snapshot_hash
       OR NEW.selection_context IS DISTINCT FROM OLD.selection_context THEN
        RAISE EXCEPTION 'Selection lineage is immutable';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER selection_lineage_immutable BEFORE UPDATE ON experiment_batches
FOR EACH ROW EXECUTE FUNCTION protect_selection_lineage();
