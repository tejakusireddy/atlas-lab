# Local campaign API

From the repository root:

```sh
make setup
make db-up
make migrate
uv run --locked atlas-register data/snapshots/doyle2018-v1
ATLAS_LOCAL_DEMO_AUTH=true uv run --locked atlas-api
```

The API binds to `127.0.0.1:8000`; interactive OpenAPI documentation is at `/docs`. Import the dataset first if the snapshot does not exist. Registration verifies candidate and quality-report checksums, source provenance, uniqueness, and eligible-group counts. It registers only outcome-free metadata; it does not read oracle measurements. Snapshot identity is bound to the manifest checksum, and repeat registration is idempotent.

The explicitly enabled local identity profile recognizes `Bearer local-scientist`, `Bearer local-reviewer`, and `Bearer local-viewer`. These are demonstration identities, not secrets or production authentication. Keep the listener on loopback. Without `ATLAS_LOCAL_DEMO_AUTH=true`, authenticated routes return 503 until a production identity provider is implemented.

```sh
curl -H 'Authorization: Bearer local-scientist' http://127.0.0.1:8000/v1/datasets
```

Use a returned snapshot/group pair in `POST /v1/campaigns`, with `Authorization: Bearer local-scientist` and a unique `Idempotency-Key`. The request accepts `dataset_snapshot_id`, `campaign_group_id`, `seed`, an observed-yield maximization objective, and a budget of at most 48 unique experiments with batches of at most eight. Only historical replay with protocol simulation is accepted as the requested mode.

A successful response contains a durable `DRAFT` campaign. `GET /v1/campaigns` supports `limit` and `offset`; `GET /v1/campaigns/{id}` is owner-scoped. Repeating a creation request with the same identity/key/body returns the same campaign. Changing the body under that key returns 409. Authentication failures return 401, role failures 403, missing/other-owner resources 404, and invalid commands 422.

Responses include `data`, `errors`, and `meta` with request ID, correlation trace ID, and schema version. Trace IDs currently correlate API/audit records; distributed tracing export is not yet implemented. `/health/live`, `/health/ready`, and `/v1/system/capabilities` expose operational status. Capabilities explicitly distinguish unimplemented simulation/oracle features and unconfigured NVIDIA providers.

The API supports draft creation, planning, independent review, and queued simulation. Historical measurement release is available through a separate worker; reports remain pending.

## Planning and review

`POST /v1/campaigns/{id}/plan` accepts `{"expected_version": 0}` for a new draft plus an idempotency key. The initial planner is a seeded random baseline over the registered candidate pool. It persists a water-placeholder work order and returns `AWAITING_APPROVAL`, `run_spec`, and `plan_hash`. The campaign version advances; read it again before another mutation. After analysis, the next proposal must also include `previous_snapshot_hash` from the latest committed analysis.

A reviewer lists `/v1/approvals/pending` or reads `/v1/campaigns/{id}/batches/{batch_id}`. Approve or reject by posting `{"expected_version": 0, "plan_hash": "sha256:..."}` to the corresponding `/approve` or `/reject` endpoint with a new idempotency key. The reviewer must differ from the proposer. The hash must match the full immutable work order; stale versions and changed hashes conflict. Approvals expire after one hour and must be rechecked before dispatch.

Approval transactionally reserves unique candidate IDs against the campaign budget and creates an approved run with an audit event. `budget_used` currently means reserved unique selections, not observed measurements. Rejection leaves the budget unchanged and allows a new proposal revision. The previous batch must be rejected or analyzed before another proposal is accepted. Approved runs can be queued for simulation; see the [historical results runbook](historical-results.md) for measurement release.

## Dispatch and recovery

Post `{"expected_version": 0}` to `/v1/runs/{run_id}/simulate` as the owning scientist with an idempotency key. The 202 response records dispatch intent transactionally. Build the worker with `make sim-image`, then run `uv run --locked atlas-worker` to process one queued run. Each invocation claims at most one dispatch; it does not run a polling daemon.

Read `/v1/runs/{run_id}` and `/v1/runs/{run_id}/events` for status and ordered transitions. Approval validity is checked again immediately before claiming execution. A claimed run has one attempt and a five-minute lease. Run `uv run --locked atlas-worker --recover-expired` to mark expired attempts `EXECUTION_UNKNOWN`; this never dispatches them again.

A reviewer can post the current `expected_version` to `/v1/runs/{run_id}/reconcile` with an idempotency key. Reconciliation accepts only a durable receipt from the registered attempt directory matching the run, protocol hash, and simulator version. Without matching evidence the outcome remains unknown. Keep artifact directories on trusted local storage: receipts are local worker evidence, not cryptographically signed attestations.

Run `make workflow` to verify the full HTTP → PostgreSQL → real simulator flow in an isolated test schema.
