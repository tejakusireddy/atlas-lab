# Historical outcome release

After `make migrate`, run the outcome worker separately from the API and planner:

```sh
uv run --locked atlas-reveal RUN_UUID --snapshot data/snapshots/doyle2018-v1
```

Only a `SIMULATED` run in an active campaign is eligible. Reserved candidate IDs must match its immutable work order. The worker verifies the registered manifest and outcome-file checksums before releasing selected rows. Repeated release returns the existing immutable measurements.

QC checks source row/file provenance, units, numeric range, and agreement between raw and normalized yield. Missing rows remain `UNOBSERVED`; invalid and synthetic records are retained but excluded from `training_observations`. Simulator command logs never supply reaction yields.

Read released records through the owner-scoped `GET /v1/campaigns/{id}/measurements` endpoint. The API and planner do not import the outcome worker. The local profile shares an operating-system user and database credentials; separate filesystem mounts and least-privilege database roles remain deployment work. Do not treat process separation as an enforced security boundary.

Release ends at `QC_COMPLETE`. Analysis and subsequent model updates are separate operations.
