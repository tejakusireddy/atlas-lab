# Historical outcome release

After `make migrate`, run the outcome worker separately from the API and planner:

```sh
uv run --locked atlas-reveal RUN_UUID --snapshot data/snapshots/doyle2018-v1
```

Only a `SIMULATED` run in an active campaign is eligible. Reserved candidate IDs must match its immutable work order. The worker verifies the registered manifest and outcome-file checksums before releasing selected rows. Repeated release returns the existing immutable measurements.

QC checks source row/file provenance, units, numeric range, and agreement between raw and normalized yield. Missing rows remain `UNOBSERVED`; invalid and synthetic records are retained but excluded from `training_observations`. Simulator command logs never supply reaction yields.

Read released records through the owner-scoped `GET /v1/campaigns/{id}/measurements` endpoint. The API and planner do not import the outcome worker. The local profile shares an operating-system user and database credentials; separate filesystem mounts and least-privilege database roles remain deployment work. Do not treat process separation as an enforced security boundary.

Release ends at `QC_COMPLETE`. The owner posts the current run `expected_version` to `/v1/runs/{run_id}/analyze` with an idempotency key. This freezes a hash-bound snapshot of released, QC-passed historical observations, QC counts, and the best observed yield with its measurement ID. No observations means no best yield, rather than an invented zero.

Analysis advances the run to `ANALYZED`, allowing another proposal. Read the new campaign version before planning. Once the reserved budget is exhausted and the final batch is analyzed, the campaign becomes `COMPLETE`; this means budget completion, not that all outcomes passed QC. Read snapshots at `/v1/campaigns/{id}/analyses`.

The current live selection policy remains seeded random and snapshots explicitly have no model revision. Model-guided selection is pending.

## Six-batch local verification

With the Doyle snapshot registered, migrations applied, and simulator image built:

```sh
uv run --locked python scripts/verify_closed_loop.py
```

This verification fixture creates a new local campaign and scripts the separate scientist/reviewer demo identities for all six batches. It exercises service transactions and the real Docker simulator; it is not evidence of human review or a full HTTP workflow. Keep the dispatch queue empty before running it. It requires 48 unique, QC-passed historical measurements, verifies budget completion, and writes hashes and run IDs to `artifacts/closed-loop-verification.json`. Each invocation retains its run artifacts and creates a new campaign. A separate `make workflow` test covers HTTP approval and dispatch.
