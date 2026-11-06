# Expanded retrospective evaluation protocol v1

This protocol is committed before running the expanded evaluation. It does not modify policy hyperparameters or the scientific reference.

- Cohort: all 12 groups in the union of the original train, calibration, and campaign partitions at split seed 42. The three predictive-test groups are excluded.
- Source: the same checksum-verified Doyle snapshot used by scientific reference v1. No new yields, synthetic labels, or external training records are introduced.
- Policies: random, diversity, greedy, ensemble UCB, with the existing versioned acquisition implementation.
- Predictors: Random Forest and CatBoost, using their frozen configurations. Neither result selects or promotes a model automatically.
- Pairing: seeds 11, 23, 42, 67, and 101; identical initial eight candidates, group candidate pools, observation rules, and budget 48.
- Checkpoints: 8, 16, 24, 32, 40, 48. Publish all policies and checkpoints.
- Metrics: mean best observed yield, historical-pool simple regret, and paired improvement over random. Average seeds within each group before 2,000 paired group-bootstrap resamples.
- Failure analysis: retain every negative paired comparison at every checkpoint. Record ensemble spread versus selected-point absolute error, including descriptive correlation and the fraction of errors within one spread. These are diagnostics, not calibrated coverage claims.
- Outputs: all trajectories, scored decisions, fitted models, paired comparison rows, negative cases, uncertainty diagnostics, summaries, split/source/lock/code identifiers, and artifact hashes. Do not overwrite prior evaluation directories.

This is an exploratory expansion. Added groups appeared in earlier development work; they are not newly untouched holdouts. All groups share one amine, so increasing substrate-pair count does not establish independence across both reactants or across data sources. The original three-group results remain separately published. This protocol broadens the retrospective evidence without relabeling development groups as prospective validation.

```sh
uv run --locked python -m atlas_science.live_benchmark --cohort exploratory_development \
  --predictor random_forest --output artifacts/expanded-rf-v1
uv run --locked python -m atlas_science.live_benchmark --cohort exploratory_development \
  --predictor catboost --output artifacts/expanded-catboost-v1
```

The curated BH-HTE-OOD source is a candidate for a later source-independent cohort, but its catalyst/solvent schema differs from this reference's role contract and includes the Doyle rows. Before adding it, verify original-record provenance and data licensing, normalize condition identities including additives, and audit cross-source duplicates. Its [pinned README](https://github.com/schwallergroup/bh-hte-ood/blob/3a44e398d9fed3f08cf396f1153be2960193f581/README.md) describes the source-aware benchmark and shared sources. Existing derived product features and outcome labels must never become planner inputs. It is not enabled as training data or benchmark evidence here.

The [completed expanded results](expanded-acquisition-results.md) and [external-source census](external-cohort-census.md) retain the measured outcomes and source-eligibility boundaries.
