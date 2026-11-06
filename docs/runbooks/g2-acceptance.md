# G2 local-profile acceptance record

Recorded 2026-11-05. This record describes demonstrated guarantees for the isolated local deployment, with production rollout requirements listed below.

| Gate | Executed evidence |
| --- | --- |
| Oracle file isolation | Non-root release UID reads a private read-only volume; API/planner/trainer UIDs fail both absent-mount and accidental-mount probes. Actual Compose service launch probes pass. |
| Isolated deployment | A real eight-selection greedy campaign completed through container API, reviewed work order, trusted host dispatch, real vendor simulation, private-volume release worker, QC, and model analysis. |
| Process recovery | Three subprocess probes cover death before simulation, lost acknowledgment after simulation, and post-simulation connection loss. No claim is redispatched; matching receipts reconcile safely. |
| Transaction recovery | A full greedy campaign survives lost acknowledgment and failed training analysis, then matches the uninterrupted repeat. Incomplete analysis never unlocks planning. |
| Trace propagation | A child process joins the saved W3C parent and exports through an actual OTLP HTTP receiver. Full workflows retain campaign trace roots and omit injected private exception messages. |
| Scientific freeze | Five configurations each pass two complete six-batch campaigns against pre-G2 golden trajectory hashes, source/lock hashes, code hashes, receipt hashes, and snapshot lineage. |
| Expanded evaluation | Twelve retrospective groups, five paired seeds, four policies, both predictors, and all six checkpoints. All negative cases and uncertainty diagnostics retained. |
| Quality checks | Ruff, strict mypy, 34 unit tests, 17 scientific tests, 17 database/OTLP integration tests, five reference cases, three process-fault cases, and one isolation case pass. The dependency audit reports no known vulnerabilities in auditable third-party packages; local workspace packages have no PyPI advisory identity. |

The reference suite's five cases contain 60 actual vendor simulation batches. Benchmark trials separately evaluate the same acquisition engine offline; they do not add simulated chemistry claims. [Expanded results](../reproducibility/expanded-acquisition-results.md) preserve the negative and inconclusive findings. [Scientific reference v1](../reproducibility/scientific-reference.md) is mandatory before later orchestration or model integrations.

## Local operational evidence

The container API is available on host loopback port 8001; PostgreSQL remains on loopback 55432. The smoke campaign is `c4680f2a-5577-4590-9cc5-fab1be9eb8e8`, run `d38615fc-300a-48d8-8061-a074e9233db3`. Its committed snapshot hash is `sha256:0d619168a8c49d4d50f94c6db20a0f12a17853b8ea51c3f0da8fd5ac4a812792`. The locally retained evidence is `artifacts/isolated-smoke/evidence.json`; run receipts, model bytes, and measurements remain linked in PostgreSQL and ignored artifact storage.

Reproduce the component checks with `make check`, `make integration`, `make sim-image`, `make faults`, `make runtime-image`, `make isolation`, and `make reference-workflow`, after the pinned dataset import and database migration. Run `make audit` for the dependency advisory check. See the [isolation](oracle-isolation.md), [recovery](execution-recovery.md), and [tracing](observability.md) runbooks for setup and specific boundaries.

## Production rollout boundaries

The workstation owner, Docker daemon, provisioning operator, and host dispatcher remain trusted. Containers have no Docker socket, repository mount, or outcome access except the release volume. The host development profile does not inherit container isolation. The local profile still uses demonstration identities and database credentials; production identity, secrets, least-privilege database roles, and a constrained dispatch broker remain deployment requirements.

OTLP propagation/export is tested; a production collector, dashboards, metrics/log aggregation, disaster-recovery topology, and measured production SLOs are not claimed. Additional source-independent chemical evidence requires original-record provenance and licensing plus source-aware normalization; the twelve-group expansion is explicitly exploratory. These boundaries do not weaken or replace the frozen scientific regression gates.
