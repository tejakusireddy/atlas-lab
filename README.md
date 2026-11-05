# ATLAS Lab

**Autonomous Laboratory & Scientific Discovery Platform**

ATLAS is a simulation-first reaction optimization platform designed to connect experiment selection, reviewed work orders, Opentrons protocol simulation, historical measurement replay, and reproducible scientific reporting.

The reference campaign targets Buchwald–Hartwig reaction conditions for a held-out substrate pair: up to 48 unique historical candidates, selected in batches of eight. Observed yields come from published experimental records. Robot simulation validates representative liquid-handling protocols; it does not generate chemical measurements.

## Project status

**Early development; application implementation has not started.** There is no runnable application, validated migration, or measured benchmark yet.

| Deliverable | Status |
| --- | --- |
| Development tooling and CI | Next |
| Dataset import, split validation, and CPU baselines | Planned — G0 |
| Approved simulation and historical replay loop | Planned — G1 |
| Durable execution, reconciliation, and telemetry | Planned — G2 |
| NVIDIA integrations and model lifecycle evaluation | Planned — G3 |
| Research evaluation and demonstration artifacts | Planned — G4 |

## Architecture

The target system uses a React/TypeScript workbench and a modular FastAPI application. PostgreSQL owns campaign state, approvals, measurement provenance, and transactional outbox events. Isolated workers handle protocol simulation and model training. Content-addressed artifacts retain data, protocol, model, and report lineage.

The local reference profile must run on CPU without cloud credentials or physical laboratory equipment. Historical campaign outcomes remain isolated from planning and training until eligible selections have completed simulation. Missing measurements remain unobserved; only source-backed, QC-passed observations enter scientific model updates.

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

Changes are delivered as small, independently validated commits. The README tracks implemented capabilities and setup instructions as they become available. See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines.

## Scientific scope

The public reference profile simulates representative nonhazardous liquid handling and replays independently published historical outcomes. It does not operate wet-lab hardware, simulate reaction chemistry, or establish prospective discovery or physical safety. Benchmark results and integration claims will be published only with reproducible evidence.

## License

Repository code is licensed under [Apache-2.0](LICENSE). External datasets, model weights, and vendor assets retain their respective licenses; their access and redistribution terms must be verified before import or distribution.
