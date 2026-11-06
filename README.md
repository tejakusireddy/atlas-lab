# ATLAS Lab

**Autonomous Laboratory & Scientific Discovery Platform**

ATLAS is a simulation-first reaction optimization platform designed to connect experiment selection, reviewed work orders, Opentrons protocol simulation, historical measurement replay, and reproducible scientific reporting.

The reference campaign targets Buchwald–Hartwig reaction conditions for a held-out substrate pair: up to 48 unique historical candidates, selected in batches of eight. Observed yields come from published experimental records. Robot simulation validates representative liquid-handling protocols; it does not generate chemical measurements.

## Project status

**Foundations in development.** The Python workspace provides deterministic artifact hashing, local quality checks, and a checksum-verified Doyle dataset importer. PostgreSQL campaign persistence and migrations are available; the HTTP API supports registered datasets and owner-scoped campaign drafts. Planning, independent review, and durable dispatch to the real Opentrons simulator are available. Checksum-verified historical outcome release, immutable QC records, and analysis snapshots with receipt and prior-snapshot lineage are available. Random, greedy, diversity, and ensemble-UCB campaigns are implemented; Random Forest and CatBoost model artifacts are retained with decision provenance.

| Deliverable | Status |
| --- | --- |
| Python tooling and CI configuration | Local checks pass; hosted CI verified for the published main revision below |
| Doyle dataset import and provenance | Available; 4,312 candidates across 15 eligible groups |
| Group splits and finite-pool selection | Available with leakage, uniqueness, and budget checks |
| CPU predictive baselines | Random Forest and CatBoost evaluation available |
| Sequential evaluator | Random, diversity, greedy, and ensemble acquisition implemented |
| PostgreSQL campaign persistence | Available with idempotency, audit, and outbox transactions |
| Campaign HTTP API | Dataset registration, drafts, immutable plans, and independent approvals |
| Simulation work orders | Validated contract, deterministic compiler, and tested Opentrons worker |
| Approved simulation and historical replay loop | Reproducible six-batch HTTP workflow verified twice against real source data and simulator |
| Durable execution, reconciliation, and telemetry | Process-loss recovery probes and opt-in OpenTelemetry export verified |
| Production identity, secrets, database roles, and constrained dispatch | Open rollout blockers; Cognito verification, database grants and constrained broker implemented; AWS rollout pending; [acceptance requirements](docs/runbooks/production-rollout.md) |
| NVIDIA integrations and model lifecycle evaluation | Planned — G3 |
| Research evaluation and demonstration artifacts | Planned — G4 |

Hosted CI passed for `main` commit `36b5f7d4ddb49cde1e49f2afe14f747ba95d4cfe` on 2026-11-05 ([verified run](https://github.com/tejakusireddy/atlas-lab/actions/runs/42071960495)). The newer G2 additions through local commit `1781a8b` have local acceptance evidence; hosted verification of those additions is pending their push. CI success applies to the tested commit, not automatically to later local work.

## Architecture

The target system uses a React/TypeScript workbench and a modular FastAPI application. PostgreSQL owns campaign state, approvals, measurement provenance, and transactional outbox events. Isolated workers handle protocol simulation and model training. Content-addressed artifacts retain data, protocol, model, and report lineage.

The local reference profile must run on CPU without cloud credentials or physical laboratory equipment. Historical campaign outcomes remain isolated from planning and training until eligible selections have completed simulation. Missing measurements remain unobserved; only source-backed, QC-passed observations enter scientific model updates.

## Local database

```sh
make db-up
make migrate
make integration
```

The production identity path verifies Cognito access tokens and rejects local demonstration identities. Production credential configuration uses a reloadable secret file and rejects development defaults. Explicit application/release/dispatch database grants have PostgreSQL allow/deny coverage. The production broker uses a dedicated Linux/rootless worker; deployment-specific AWS configuration is maintained outside the repository; see the [rollout requirements](docs/runbooks/production-rollout.md#database-credential-interface).

Requires Docker Desktop. See the [local database runbook](docs/runbooks/local-database.md) for connection settings and test isolation.

## Local API

After importing the dataset and migrating the database:

```sh
uv run --locked atlas-register data/snapshots/doyle2018-v1
ATLAS_LOCAL_DEMO_AUTH=true uv run --locked atlas-api
```

These commands start the host development profile. The two supported local profiles use different host ports:

| Profile | Base URL | Interactive API documentation |
| --- | --- | --- |
| Host development (`atlas-api`) | `http://127.0.0.1:8000` | [Host API docs](http://127.0.0.1:8000/docs) |
| Isolated Docker runtime | `http://127.0.0.1:8001` | [Isolated API docs](http://127.0.0.1:8001/docs) |

For the isolated profile, build and provision it using the [isolation runbook](docs/runbooks/oracle-isolation.md), then start the API:

```sh
docker compose -f infra/compose/compose.yaml -f infra/compose/isolated.yaml up -d api
```

Docker maps host loopback port 8001 to container port 8000. The host development process does not inherit the container's oracle isolation. See the [local API runbook](docs/runbooks/local-api.md) for authentication, requests, and profile selection. The API exposes `/docs` and `/health/ready`; the React workbench remains planned.

## Dataset import

```sh
uv run --locked atlas-import --download
```

This explicitly downloads pinned public source files into ignored local storage and creates a new normalized snapshot. See [import provenance and limitations](docs/reproducibility/doyle-import.md). Outcome records are stored separately from candidate inputs.

## CPU baselines

```sh
uv run --locked atlas-baseline --output artifacts/baseline-42 --seed 42
```

Produces held-out predictions, metrics, models, provenance manifests, and MLflow runs. See [evaluation procedure and limitations](docs/reproducibility/cpu-baselines.md).

## Sequential evaluation

```sh
uv run --locked atlas-benchmark --output artifacts/sequential-5-seeds
```

Runs paired policies on historical candidates, with eight shared initial selections and a 48-selection budget. See [benchmark scope and limitations](docs/reproducibility/sequential-benchmark.md). This evaluator does not execute robot simulations.

## Simulation work orders

The first Flex profile compiles validated water-placeholder transfers from immutable typed work orders. The [generated schema](contracts/experiment_runspec.schema.json) and [approval hash decision](docs/adr/001-approval-hash-boundary.md) define the supported boundary. The isolated Opentrons 10.1.0 worker passes real one-, eight-, and 96-transfer simulation tests. See the [simulator runbook](docs/runbooks/simulator.md). Approved runs dispatch through the PostgreSQL outbox. `make workflow` verifies HTTP approval and dispatch through the real simulator.

## Deterministic reference milestone

After importing the pinned Doyle snapshot and building the simulator image, run `make reference-workflow`. The test creates two isolated campaigns through the HTTP API, each with six independent-role approval gates, six real Docker simulations, and 48 unique source-backed observations. It compares candidate/outcome trajectories for the same seed, verifies receipt and snapshot hashes, rejects stale snapshot references and exhausted budgets, and guards oracle-file access outside the release worker. Integration tests also exercise concurrent completion/proposal requests and failure before commit.

The seeded-random selector remains the reference. Greedy, diversity, and ensemble-UCB workflows are verified alongside it; model-backed runs use Random Forest or CatBoost. See [live acquisition](docs/reproducibility/live-acquisition.md). LangGraph and NVIDIA integration work is deferred until this deterministic reference is established and retained as a regression gate. CI includes the reference test. Hosted validation of the newer G2 gates is pending; the verified published revision is recorded in Project status.

Paired live-engine evaluation is available for both predictors: four strategies, five seeds, and three held-out groups. See the [original results](docs/reproducibility/live-acquisition-results.md), [twelve-group exploratory expansion](docs/reproducibility/expanded-acquisition-results.md), and [frozen scientific reference](docs/reproducibility/scientific-reference.md). The profile currently uses campaign-local released labels only.

## NVIDIA delivery scope

NVIDIA integrations are planned deliverables with explicit evaluation requirements:

| Integration | Purpose | Required evidence |
| --- | --- | --- |
| BioNeMo MolMIM | Molecular representations for yield prediction | RDKit-only, MolMIM-only, and combined comparisons on identical splits |
| Nemotron | Constrained planning and typed tool use | Held-out workflow correctness, policy compliance, latency, and usage measurements |
| CUDA / PyTorch | GPU predictor training | Reproducible model artifacts and quality/performance comparisons against CPU baselines |
| Triton | Versioned predictor serving | Validated inference outputs and measured latency/throughput |
| Isaac Sim | Optional generic robotic workcell demonstration | Scene artifacts and collision/reachability evidence, separate from Opentrons simulation |

The CPU baseline establishes the comparison point for these integrations. Provider availability, model quality, and performance will be reported from executed evaluations.

## Development

Requires Python 3.11 and uv 0.10.4. From the repository root:

```sh
make setup
make check
make audit
uv run pre-commit install
```

`make check` runs Ruff, strict mypy, unit tests, and scientific integrity tests. Dependencies are pinned in `uv.lock`; CI uses the same commands. Install the optional Git hooks with the final command.


Changes are delivered as small, independently validated commits. The README tracks implemented capabilities and setup instructions as they become available. See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines.

## Scientific scope

The public reference profile simulates representative nonhazardous liquid handling and replays independently published historical outcomes. It does not operate wet-lab hardware, simulate reaction chemistry, or establish prospective discovery or physical safety. Benchmark results and integration claims will be published only with reproducible evidence.

## License

Repository code is licensed under [Apache-2.0](LICENSE). External datasets, model weights, and vendor assets retain their respective licenses; their access and redistribution terms must be verified before import or distribution.

Historical outcomes are released by a separate worker after successful simulation. See the [historical results runbook](docs/runbooks/historical-results.md) for QC, provenance, and local isolation limits.

The [isolated runtime](docs/runbooks/oracle-isolation.md) enforces private oracle mounts and UID permissions. See [recovery evidence](docs/runbooks/execution-recovery.md) and [campaign tracing](docs/runbooks/observability.md) for tested guarantees and deployment boundaries.

The [production security implementation record](docs/runbooks/production-security-acceptance.md) separates locally verified controls from pending AWS and rootless-worker deployment acceptance.

The [G2 acceptance record](docs/runbooks/g2-acceptance.md) lists verified isolation, recovery, tracing, and scientific gates alongside remaining production rollout requirements.

## Molecular representation evaluation

The [MolMIM evaluation protocol](docs/reproducibility/molmim-evaluation.md) defines paired RDKit/MolMIM/combined comparisons and an outcome-free input inventory. Provider execution and scientific results are **not run**; the current campaign reference continues to use RDKit. NVIDIA execution remains opt-in after environment access and a compute budget are available.
