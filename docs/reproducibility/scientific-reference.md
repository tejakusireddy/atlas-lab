# Scientific reference v1

The active runtime contract is `contracts/scientific_reference.v1.1.json`; the original `contracts/scientific_reference.v1.json` is preserved unchanged. It binds the source manifest, candidate and oracle partitions, dependency lock, scientific engine/feature/selection source files, split/campaign seeds, group identity, and 48-selection budget. Expected trajectory hashes were derived from the committed evaluations at `4c01f6a5f8401ea99a657ac7260f7a10ffa1642e`, before G2 instrumentation and recovery changes.

`make science` checks the lock and scientific code hashes. `make reference-workflow` checks five configurations through HTTP, independent-role approval, actual vendor simulation, historical release, QC, immutable analysis, and model selection. Each runs twice. Scientific comparison includes the exact ordered selections and best observed yield at all six checkpoints. Execution UUIDs, timestamps, spans, and serialized model bytes are intentionally excluded from the scientific comparison; their separate hashes and lineage remain verified.

The greedy reference includes a killed worker with lost acknowledgment and a failed training transaction. Recovery must still reproduce the existing golden trajectory. Traces must propagate through the workflow and omit private payloads. The expected hashes are checked-in constants; tests never regenerate them.

A dependency or scientific algorithm change that changes this reference requires an explicit contract revision, a complete paired evaluation, documented reasons, and preservation of the old contract and results. A failing golden comparison is investigated rather than accepted by updating expected values automatically. Observability and infrastructure changes may proceed only while the frozen regression remains passing. LangGraph and NVIDIA integrations remain deferred until these gates are retained and passing.

## Runtime revision v1.1

This revision adds PyJWT 2.15.1 for Cognito signature and claim verification. No existing dependency versions, scientific source files, datasets, seeds or expected trajectory hashes change. The new contract binds the updated lock and the predecessor contract hash; tests require every scientific field to match v1. The full paired six-batch regression passed for all five configurations (ten campaigns, sixty vendor-simulated batches) on this revision. The original five trajectory hashes remain unchanged. This is a security dependency change, not a new scientific performance claim.
