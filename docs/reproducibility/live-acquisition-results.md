# Campaign-local acquisition results

Recorded 2026-11-05 using committed evaluator `4c01f6a5f8401ea99a657ac7260f7a10ffa1642e` with a clean working tree. Both model profiles use only released campaign labels; external training is disabled.

Each predictor evaluation contains 60 policy runs (four policies × five seeds × three held-out groups), with 48 unique selections per run and six checkpoints. The initial eight selections are identical across policies for each group/seed. Seeds: 11, 23, 42, 67, 101; split seed: 42. Both evaluations together contain 720 checkpoints.

| Predictor | Policy | Mean best yield (%) | Mean simple regret (pp) | Improvement over random (pp) | Paired group-bootstrap 95% interval (pp) |
| --- | --- | ---: | ---: | ---: | --- |
| rf | random | 53.90 | 6.48 | 0.00 | [0.00, 0.00] |
| rf | greedy | 55.67 | 4.71 | 1.77 | [-5.27, 8.78] |
| rf | diversity | 56.43 | 3.95 | 2.53 | [1.64, 3.33] |
| rf | ensemble_ucb | 60.16 | 0.23 | 6.25 | [3.06, 9.53] |
| catboost | random | 53.90 | 6.48 | 0.00 | [0.00, 0.00] |
| catboost | greedy | 58.45 | 1.94 | 4.55 | [1.80, 8.78] |
| catboost | diversity | 56.43 | 3.95 | 2.53 | [1.64, 3.33] |
| catboost | ensemble_ucb | 55.79 | 4.59 | 1.89 | [-5.07, 8.78] |

Simple regret uses the historical optimum within each campaign group, accessible only to the evaluator. Seeds are averaged within each group before 2,000 paired group-bootstrap resamples. These are descriptive retrospective results from three groups, with limited uncertainty resolution; they do not establish prospective or broad chemical generalization. The dataset shares a fixed amine. No hyperparameter search or model promotion was performed on these results.

The raw summaries also contain uncertainty intervals for best observed yield and simple regret. Random and diversity are predictor-independent controls. Greedy performance must be interpreted using its interval rather than its positive mean alone.

The evaluator invokes the same acquisition implementation used by live campaigns. It does not simulate robots for all benchmark trials. Separately, the HTTP/Docker reference suite passed two six-batch campaigns for each of random, greedy, diversity, and ensemble UCB with Random Forest, plus ensemble UCB with CatBoost: 60 actual simulation batches with receipt, lineage, hidden-file-access, and reproducibility assertions.

## Reproduction and artifacts

See [commands and methodology](live-acquisition.md). Local artifacts are retained in `artifacts/live-rf` and `artifacts/live-catboost`: trajectories, full score records, fitted model bytes, split manifests, and metric summaries. Every recorded artifact checksum was verified after execution. Output directories are ignored by Git and are never overwritten by the evaluator.

| Profile | Manifest SHA-256 |
| --- | --- |
| rf | `51458dbd609864b217a30bd3e37a489837487d1019cd4f7ef304b832a51e9657` |
| catboost | `65e929d51ed98137933bb6848baedc4d671e5a4637513ca8eaf8b784671165c8` |
