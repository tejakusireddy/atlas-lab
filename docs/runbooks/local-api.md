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

The API currently creates and reads drafts. Planning, independent approvals, execution, measurement release, and reports are not yet available.
