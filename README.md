# ATLAS Lab

**Autonomous Laboratory & Scientific Discovery Platform**

ATLAS is a simulation-first reaction optimization platform designed to connect experiment selection, reviewed work orders, Opentrons protocol simulation, historical measurement replay, and reproducible scientific reporting.

The reference campaign targets Buchwald–Hartwig reaction conditions for a held-out substrate pair: up to 48 unique historical candidates, selected in batches of eight. Observed yields come from published experimental records. Robot simulation validates representative liquid-handling protocols; it does not generate chemical measurements.

## Project status

**Foundations in development.** The Python workspace provides deterministic artifact hashing, local quality checks, and a checksum-verified Doyle dataset importer. There is no runnable campaign application, validated migration, or completed comparative benchmark yet.

| Deliverable | Status |
| --- | --- |
| Python tooling and CI configuration | Available; hosted CI pending first push |
| Doyle dataset import and provenance | Available; 4,312 candidates across 15 eligible groups |
| Group splits and finite-pool selection | Available with leakage, uniqueness, and budget checks |
| CPU predictive baselines | Random Forest and CatBoost evaluation available |
| Approved simulation and historical replay loop | Planned — G1 |
| Durable execution, reconciliation, and telemetry | Planned — G2 |
| NVIDIA integrations and model lifecycle evaluation | Planned — G3 |
| Research evaluation and demonstration artifacts | Planned — G4 |

## Architecture

The target system uses a React/TypeScript workbench and a modular FastAPI application. PostgreSQL owns campaign state, approvals, measurement provenance, and transactional outbox events. Isolated workers handle protocol simulation and model training. Content-addressed artifacts retain data, protocol, model, and report lineage.

The local reference profile must run on CPU without cloud credentials or physical laboratory equipment. Historical campaign outcomes remain isolated from planning and training until eligible selections have completed simulation. Missing measurements remain unobserved; only source-backed, QC-passed observations enter scientific model updates.

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
