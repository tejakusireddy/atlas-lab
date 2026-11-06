# Molecular representation evaluation v1

The scientific question is whether MolMIM molecular representations improve held-out yield prediction and sequential experimental decisions over the existing role-separated RDKit features. The preregistered contract is `contracts/molmim_evaluation.v1.json`. Evaluation status is **not run**. No NVIDIA model, GPU training, inference speedup or scientific improvement is claimed by preparation work.

## Input and provider coverage

The preparation command reads only the pinned source manifest and candidate inputs, validates their hashes, and emits an outcome-free molecule inventory. It never loads observations or imports the offline outcome evaluator. Existing output is never overwritten:

```sh
uv run --locked python -m atlas_science.representation_inventory \
  --snapshot data/snapshots/doyle2018-v1 \
  --output artifacts/molmim-input-inventory-v1.json
```

The Doyle snapshot contains 4,312 candidates in 15 substrate-pair groups. Forty-six distinct nonempty canonical molecule inputs require provider coverage. There are 180 candidates with an absent additive. Empty canonical SMILES means a genuinely absent role and receives an explicit zero block; it is never sent to the provider. A missing embedding for a present molecule is an error, never a zero block or an RDKit substitution. Fragmented/charged inputs and element composition are inventoried, not silently removed. Coverage and numerical validity must be measured on every required input before primary evaluation.

Use MolMIM's documented [`/embedding` endpoint](https://docs.nvidia.com/nim/bionemo/molmim/1.0.0/endpoints), whose request contains `sequences` and whose response contains `embeddings`. Its molecule-generation API is a different capability; availability of generation does not establish access to embeddings. Endpoint availability, actual model revision/container digest, vector dimension, input support and service limits must be verified in the chosen environment. No public hosted embedding endpoint or account access is assumed. No endpoint configuration, private worksheet, credentials or external source documents are added to the repository.

## Paired scientific comparisons

The arms are RDKit only, MolMIM only, and combined features. Preserve the five roles in the established order: aryl, amine, base, ligand, additive. Combined features concatenate the unchanged RDKit vector followed by role-separated embeddings. No reaction temperatures, solvent values or other conditions are invented; adding validated condition fields requires a versioned feature revision. Molecular vectors are inputs to a supervised yield predictor, not yield estimates themselves.

For prediction, retain the seed-42 group split: train on the six training groups, retain the three calibration groups for diagnostics, and compare on the three fixed OOD-test groups after settings are locked. Use the existing offline RF and CatBoost prediction heads, with identical parameters and seeds across representations and zero tuning trials. Report MAE, RMSE and rank correlation by group and paired aggregate. Earlier CPU baseline results have already inspected this test partition; this is a prespecified representation comparison on a fixed benchmark, not a newly untouched external test. The fixed amine is shared; do not claim strict unseen-substrate generalization. Document MolMIM pretraining-data overlap if known, and uncertainty if unknown.

For sequential evaluation, use the same released-label decision rules and existing live RF/CatBoost heads across all arms. Run random, greedy, diversity and ensemble UCB, five paired seeds and checkpoints 8/16/24/32/40/48. Every arm shares its initial seeded-random eight selections. External supervised training is disabled in this campaign-only profile. A model update can use only QC-passed released outcomes from selected experiments. Missing or quarantined observations remain recorded and excluded from labels. The optimizer receives candidate inputs and eligible released labels; only the evaluator may read unreleased outcomes for replay and regret. Approval, QC, snapshot and budget gates remain unchanged.

Development uses the existing 12 development groups; freeze settings before the three reserved group comparisons. The primary features are unscaled, matching the existing RDKit reference. Do not fit normalization or PCA on test/candidate pools. Any normalization/dimensionality-reduction sensitivity study needs a declared secondary protocol and training-only fitting, never a hidden adjustment to rescue one arm. Diversity is representation-sensitive; the random policy is a paired negative control and must reproduce selections across arms.

Report all groups, seeds, arms and checkpoints, including failures and negative effects. Average paired seeds within each held-out group, then bootstrap groups with seed 42 and 2,000 resamples for 95% intervals. Three test groups provide limited uncertainty evidence; do not treat repeated seeds as independent chemical groups. Tree/ensemble spread remains an acquisition heuristic, not calibrated predictive uncertainty. Simple regret uses the source-backed eligible group optimum in the evaluator only.

Primary comparison requires complete embedding coverage of all nonempty inputs. If the provider cannot represent the full input set, record primary evaluation as blocked/not run. A separately labeled secondary coverage analysis may use an outcome-blind support mask shared across every arm, reporting all exclusions and retaining at least 48 candidates per included group. Never compare an embedding-compatible subset against an unrestricted RDKit baseline.

## Provenance, resources and acceptance

Bind candidate/split/feature/training hashes, role layout, preprocessing version, immutable model revision, embedding dimension, raw response hashes, exact head settings, seeds and scientific trajectory lineage. A cache identity includes canonical SMILES, provider, model name/revision and preprocessing version. A model revision or preprocessing change invalidates its cache identity. Reject duplicate inputs, missing/extra/reordered response rows where detectable, shape drift and nonfinite values. Test fixtures are explicitly synthetic evidence and cannot become production embedding artifacts by default.

Measure cold embedding time separately from cache reads and predictor fitting. Report requests/failures, feature storage, process peak memory, hardware/software, and measured GPU time/VRAM/cost when available. Unavailable measurements are null/not measured, never zero. Fix seeds and thread budgets; report feature dimensionality and equal head settings rather than assuming equal wall-clock work. Do not claim GPU speedup from comparisons between different algorithms or unmatched workloads.

Acceptance requires real versioned provider responses, validated input coverage, reproducible feature artifacts, matched held-out prediction and sequential results, preserved scientific reference tests and a complete resource report. No automatic promotion follows a better average; assess group failures and uncertainty. A negative or inconclusive result is acceptable scientific evidence. CUDA/PyTorch, Triton and Nemotron remain separate later changes. Isaac Sim remains optional.
