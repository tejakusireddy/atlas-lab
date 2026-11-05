# Isolated Opentrons simulation

```sh
make sim-image
make sim
uv run --locked atlas-simulate artifacts/eight-transfer-spec.json --output artifacts/eight-transfer-run
```

The CLI requires a valid `RunPlan` JSON file and a new output directory. The example filename above is illustrative; supply your reviewed work order. `make sim` constructs synthetic work orders and verifies one-, eight-, and 96-transfer protocols against the real vendor simulator.

The worker uses Opentrons 10.1.0 in a separate Python 3.12 environment, with a pinned base-image digest and hash-locked dependencies. The first integration attempt on Python 3.11 failed in vendor TypedDict definitions under the resolved Pydantic version. Python 3.12 passed all three golden simulations. The application and scientific stack remain on Python 3.11 and are not installed inside the worker.

Containers run without network access, as a non-root user, with read-only root/input filesystems, no added Linux capabilities, and bounded CPU, memory, process count, and temporary storage. Only the work-order output directory is mounted; do not place credentials or datasets in that directory. The runner always compiles its own protocol from a validated plan and does not accept arbitrary Python input.

Each attempt retains `protocol.py`, `run_spec.json`, stdout/stderr logs, and `simulation_manifest.json` with plan/protocol hashes, immutable local image ID, simulator version, and command log. Actual vendor command logs are the evidence of simulation. No yield values are produced.

Timeouts record `EXECUTION_UNKNOWN` and never automatically retry. The container name includes the run ID; inspect that container and retained artifacts before deciding any recovery action. The standalone runner does not provide durable cross-process idempotency or automated reconciliation. Those belong to the application execution coordinator. It refuses to overwrite an existing attempt directory.

A successful simulation validates this representative protocol against vendor software. It does not establish chemical outcomes, calibrated physical accuracy, or permission to operate hardware.
