# Contributing

## Engineering baseline

The project specifications are maintained outside this repository. Use them as implementation references; do not copy the supplied documents or starter files into the repository. Repository documentation should describe the implementation and its validated behavior.

Record material design changes with rationale, affected requirements, and validation. Resolve discrepancies between descriptive requirements and starter designs before implementing the affected behavior.

BioNeMo MolMIM, Nemotron, and Triton are planned integration deliverables, with CUDA/PyTorch supporting the GPU predictor path. Their completion requires real integration and evaluation evidence. Isaac Sim remains optional. Preserve the CPU-only, no-credentials reference profile throughout delivery.

## Atomic changes

Each commit addresses one coherent concern and leaves the repository in a reviewable state. Separate unrelated refactors, dependency changes, and behavior changes. Establish reproducible scientific baselines before the closed loop, reliability features, and NVIDIA evaluation milestones.

Before committing:

1. Review the diff for scope, accidental files, secrets, and unsupported claims.
2. Run the checks relevant to the change and report their actual results. Do not present planned checks as executed validation.
3. Update the README when setup, available capabilities, project status, or user-facing behavior changes.
4. Use a concise commit subject describing the engineering change and its purpose.

Keep documentation and commit messages factual. Distinguish implemented behavior from proposed architecture, measured outcomes from predictions, and historical observations from synthetic fixtures. Do not publish benchmark numbers or provider performance claims without their supporting artifacts.

## Validation and dependencies

Introduce working checks with the functionality they validate. Verify upstream versions, compatibility, and licensing when adding dependencies; commit applicable lockfiles.

Dataset ingestion must preserve source provenance and enforce the scientific split and oracle boundaries. Do not commit downloaded datasets, credentials, or vendor assets without verified distribution rights. Use explicitly labeled synthetic fixtures only for tests that do not claim scientific performance.
