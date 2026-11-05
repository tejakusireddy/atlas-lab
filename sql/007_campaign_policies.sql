ALTER TABLE campaigns ADD COLUMN acquisition_strategy TEXT NOT NULL DEFAULT 'random'
CHECK (acquisition_strategy IN ('random','greedy','diversity','ensemble_ucb'));
ALTER TABLE campaigns ADD COLUMN predictor TEXT NOT NULL DEFAULT 'random_forest'
CHECK (predictor IN ('random_forest','catboost'));
CREATE FUNCTION protect_campaign_configuration() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.acquisition_strategy <> OLD.acquisition_strategy OR NEW.predictor <> OLD.predictor
       OR NEW.seed <> OLD.seed OR NEW.snapshot_id <> OLD.snapshot_id OR NEW.group_id <> OLD.group_id
       OR NEW.budget_max <> OLD.budget_max OR NEW.batch_size <> OLD.batch_size THEN
        RAISE EXCEPTION 'Campaign scientific configuration is immutable';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER campaign_configuration_immutable BEFORE UPDATE ON campaigns
FOR EACH ROW EXECUTE FUNCTION protect_campaign_configuration();
CREATE TABLE model_artifacts (
    model_hash TEXT PRIMARY KEY CHECK (model_hash ~ '^sha256:[0-9a-f]{64}$'),
    artifact BYTEA NOT NULL,
    format TEXT NOT NULL CHECK (format='python-pickle-v5'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TRIGGER model_artifacts_immutable BEFORE UPDATE OR DELETE ON model_artifacts
FOR EACH ROW EXECUTE FUNCTION reject_reference_mutation();
