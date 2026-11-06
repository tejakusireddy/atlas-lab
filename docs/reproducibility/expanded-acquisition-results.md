# Expanded retrospective acquisition results

Protocol: [expanded evaluation v1](expanded-evaluation-protocol.md), committed before execution. Cohort: 12 existing development substrate-pair groups, with the three predictive-test groups excluded. Seeds: 11, 23, 42, 67, 101. Both profiles train only on released campaign observations.

This is an exploratory expansion, not newly untouched validation. Groups share a fixed amine and source, so the intervals describe this cohort rather than independence across reactants or data sources. Absolute means across the old and expanded cohorts reflect different candidate pools; paired differences within each cohort support comparison. The [original three-group results](live-acquisition-results.md) remain preserved.

Each profile contains 240 policy runs and 1,440 checkpoints: four policies × five seeds × 12 groups × six batches. The combined evaluation contains 480 runs and 2,880 checkpoints. Each policy has identical initial eight candidates and a 48-unique-selection budget for every group/seed.

| Predictor | Policy | Mean best yield (%) | Mean simple regret (pp) | Improvement over random (pp) | Descriptive paired group-bootstrap 95% interval (pp) |
| --- | --- | ---: | ---: | ---: | --- |
| Random Forest | random | 67.55 | 4.77 | 0.00 | [0.00, 0.00] |
| Random Forest | greedy | 70.05 | 2.27 | 2.50 | [0.51, 4.40] |
| Random Forest | diversity | 66.90 | 5.43 | -0.66 | [-2.16, 0.83] |
| Random Forest | ensemble_ucb | 71.65 | 0.67 | 4.10 | [2.47, 5.73] |
| CatBoost | random | 67.55 | 4.77 | 0.00 | [0.00, 0.00] |
| CatBoost | greedy | 71.01 | 1.31 | 3.46 | [2.00, 5.09] |
| CatBoost | diversity | 66.90 | 5.43 | -0.66 | [-2.16, 0.83] |
| CatBoost | ensemble_ucb | 70.04 | 2.28 | 2.49 | [0.59, 4.35] |

Seeds are averaged within group before 2,000 paired group-bootstrap resamples. Simple regret uses the historical optimum accessible only to the evaluator. The published summaries retain best-yield and regret intervals at all six checkpoints. This evaluation performs no new robot simulations; the separate frozen HTTP/Docker suite verifies execution and measurement gates.

## Losses and uncertainty diagnostics

| Predictor | Policy | Wins / ties / losses against random at 48 | Selected-point mean absolute error (pp) | Mean ensemble spread (pp) | Errors within one spread |
| --- | --- | --- | ---: | ---: | ---: |
| Random Forest | greedy | 41 / 9 / 10 | 12.08 | 11.69 | 60.2% |
| Random Forest | diversity | 22 / 10 / 28 | — | — | — |
| Random Forest | ensemble_ucb | 48 / 8 / 4 | 13.28 | 14.59 | 64.6% |
| CatBoost | greedy | 45 / 9 / 6 | 10.90 | 0.78 | 4.3% |
| CatBoost | diversity | 22 / 10 / 28 | — | — | — |
| CatBoost | ensemble_ucb | 44 / 8 / 8 | 11.32 | 0.81 | 4.4% |

These counts describe 60 paired runs per policy; they are not 60 independent chemical groups. All negative comparisons at all checkpoints are retained: 206 for Random Forest and 188 for CatBoost, out of 1,080 non-random paired comparisons per profile. Diversity has a negative mean difference in this expanded cohort, despite its positive original three-group result. No policy or subgroup was removed after observing outcomes.

Spread diagnostics cover 2,400 selected post-initial predictions per model-backed policy. They are affected by adaptive selection and are not a predictive calibration test. CatBoost seed spread is far smaller than observed errors, so it must not be presented as a calibrated confidence interval. Correlations by group and every paired loss are retained in the raw artifacts. No calibration, hyperparameter adjustment, or automatic model promotion was performed.

## Provenance and verification

| Profile | Local artifact directory | Manifest SHA-256 |
| --- | --- | --- |
| Random Forest | `artifacts/expanded-rf-v1-confirmed` | `abd42433a1910091fe9c84c47a26106f67cd2bc2cbb4874f388dd4cded60a589` |
| CatBoost | `artifacts/expanded-catboost-v1` | `59eda64b88825196fc702c2b052a6b2654e292c92f7666880f52e9313c9d3334` |

Both accepted manifests identify clean commit `ce5d192a82b81a362b237eb203b22f490148e0a4` and the frozen lock. Every artifact checksum and model-byte digest was verified. All 60 initial designs per profile matched across policies; all 2,880 checkpoints respected uniqueness and budget; all training IDs were previously selected; random/diversity controls matched exactly across predictor profiles. The accepted Random Forest run also exactly reproduced the initial expansion run. The earlier run is retained at `artifacts/expanded-rf-v1` with its truthful dirty-worktree flag from an infrastructure-only fix during execution.

Artifacts include full trajectories, scored decisions, fitted model bytes, paired comparisons, negative cases, uncertainty diagnostics, split manifest, source/lock/code identifiers, and checksums. They are ignored by Git, preserved locally, and never overwritten by the evaluator. Reproduction commands are in the committed protocol.
