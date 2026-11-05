# Execution recovery evidence

```sh
make db-up
make sim-image
make faults
```

The fault suite starts real subprocesses in disposable PostgreSQL schemas and intentionally exits them after dispatch claim or after real vendor simulation. A third probe closes the worker's database connection after simulation and attempts another operation. In every case the claim stays durable, the pending message cannot be reclaimed, lease expiry advances to `EXECUTION_UNKNOWN`, repeated recovery is harmless, and a new dispatch command is rejected. Reserved budget remains eight.

A completed vendor attempt can be reconciled by a reviewer from its matching durable receipt. A crash before simulation leaves no receipt and stays unknown; it is never guessed successful or automatically replayed. Receipt and reconciliation writes are transactional and idempotent. Existing integration tests cover malformed receipts, missing receipts, changed hashes, expired approvals, duplicate intent, and concurrent analysis/proposal requests.

The six-batch reference suite also kills a worker after successful simulation, reconciles the lost acknowledgment, injects a model-training exception during the next analysis, and then finishes the campaign. The recovered trajectory must match the uninterrupted repeat. A training failure leaves `QC_COMPLETE`, no analysis snapshot, and no permission to advance; retry uses the unchanged released ledger.

These probes establish specific failure guarantees. They do not reproduce a physical robot, a distributed database failover, or every network partition. Host dispatch and reconciliation storage remain trusted operator components in the local deployment.
