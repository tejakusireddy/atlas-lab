# Offline sequential benchmark

```sh
uv run --locked atlas-benchmark --output artifacts/sequential-5-seeds
```

The default evaluation uses five paired seeds, three held-out campaign groups, four policies, and a 48-selection budget in batches of eight. Each policy begins with the same seeded initial eight candidate IDs for its group/seed pair. Policies never select a candidate twice.

The deterministic split keeps campaign groups outside the external training, calibration, and predictive test partitions. The offline evaluator owns historical outcomes and passes only already-selected outcomes to the selection function. The evaluator uses the hidden pool optimum solely to calculate simple regret. This is a software boundary for offline evaluation, not the separate service boundary required for application execution.

Policies:

- Random sampling without replacement.
- Maximin diversity in role-separated binary Morgan feature space, with deterministic ties.
- Greedy Random Forest mean prediction.
- Random Forest mean plus one tree-ensemble standard deviation. This is an uncalibrated acquisition heuristic, not a statistical confidence bound.

The two learned policies fit 64 trees at each round using eligible external training records plus the campaign's revealed observations. The fixed model configuration is recorded in the run manifest. No test-set tuning occurs in this benchmark.

Outputs include selected IDs and best observed yields at 8/16/24/32/40/48 selections, simple regret, seed-averaged group summaries, group-bootstrap intervals, failure records, frozen split/source manifests, code revision/dirty state, lockfile digest, and artifact checksums. Outputs stay in ignored local artifact storage.

Three campaign groups are sufficient to exercise the evaluator, but not to fulfill the planned study across at least ten eligible campaigns. Bootstrap intervals from only three groups have limited inferential value. The shared fixed amine also prevents strict both-substrates-OOD claims. Broader group coverage, complete environment/report exports, and comparative plots remain work for the full benchmark milestone.

No robot protocol is simulated by this command. Historical outcomes in the evaluator must not be presented as results of simulated chemistry or as an executed laboratory campaign.
