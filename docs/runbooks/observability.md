# Campaign tracing

Tracing is opt-in and uses the OpenTelemetry SDK with W3C Trace Context. Campaign creation stores its carrier in PostgreSQL in the creation transaction. Proposal, review, dispatch, simulation, release, analysis, model update, and reconciliation use that saved context across requests and worker restarts. Campaigns created before tracing is enabled have no saved root; enable tracing before creating a traced campaign.

```sh
ATLAS_OTEL_EXPORTER=console OTEL_SERVICE_NAME=atlas-api \
  ATLAS_LOCAL_DEMO_AUTH=true uv run --locked atlas-api
```

For an OTLP HTTP receiver:

```sh
export ATLAS_OTEL_EXPORTER=otlp
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://127.0.0.1:4318/v1/traces
export OTEL_SERVICE_NAME=atlas-worker
uv run --locked atlas-worker
```

Configure the same exporter for each participating process. Container receivers must use a reachable network hostname rather than container loopback. SDK batch processing exports asynchronously and flushes during normal shutdown; abrupt process death can lose in-memory spans. Database run events, receipts, audit entries, and outbox intents remain the recovery authority.

Spans include operation names, durations, campaign/run IDs, and exception type. They omit molecular inputs, outcomes, candidate scores, request bodies, tokens, and exception messages/stack traces. Scientific data belongs in its access-controlled ledger, not telemetry. The API's existing `meta.trace_id` is a request correlation identifier; it is not the SDK campaign trace ID. The SDK trace parent is stored in `campaign_trace_contexts` and emitted by the configured exporter.

`make integration` verifies a child process exporting a proposal through an actual local OTLP HTTP receiver and checks the parent and trace IDs. `make reference-workflow` verifies the stage spans share their campaign roots, training errors do not leak their message, and recovery preserves the scientific trajectory. These tests establish trace propagation and export; they do not claim measured production availability, latency SLOs, a deployed collector, or a metrics/log aggregation service.

Implementation follows the official [instrumentation](https://opentelemetry.io/docs/languages/python/instrumentation/), [propagation](https://opentelemetry.io/docs/languages/python/propagation/), and [exporter](https://opentelemetry.io/docs/languages/python/exporters/) documentation.
