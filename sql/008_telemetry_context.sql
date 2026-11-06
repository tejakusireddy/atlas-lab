CREATE TABLE campaign_trace_contexts (
    campaign_id UUID PRIMARY KEY REFERENCES campaigns(id),
    carrier JSONB NOT NULL
);
CREATE TRIGGER campaign_trace_context_immutable BEFORE UPDATE OR DELETE ON campaign_trace_contexts
FOR EACH ROW EXECUTE FUNCTION reject_reference_mutation();
