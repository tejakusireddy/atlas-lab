# CPU predictive baselines

After importing the Doyle snapshot, run:

```sh
uv run --locked atlas-baseline --output artifacts/baseline-42 --seed 42
```

The evaluator verifies snapshot artifact checksums, creates a seeded substrate-pair split, and trains fixed Random Forest and CatBoost regressors using role-separated RDKit Morgan fingerprints. No product identity, source row number, or yield is included in the feature matrix. Identical sorted inputs and a single training thread support repeatability.

The 15 substrate groups are divided into six training groups, three calibration groups, three campaign groups, and three predictive test groups. Only the training partition enters model fitting. Calibration residuals set a nominal 90% interval radius. Test observations are used only to compute held-out metrics; campaign labels are not used in this evaluation. There is no hyperparameter selection on the test set.

Each output directory contains the split/source manifests, persisted model artifacts, per-record predictions and observations, and a run manifest with dependency versions, Git revision/dirty state, lockfile digest, model parameters, metrics, and artifact hashes. MLflow records parameters, metrics, models, and split manifests in a local SQLite tracking store. This SQLite database is for offline experiment tracking, not authoritative campaign state.

```sh
uv run mlflow ui --backend-store-uri sqlite:///artifacts/mlflow.db --port 5000
```

Treat exported model files as executable trusted artifacts. Only load locally generated, checksum-verified models; never load untrusted joblib/pickle files.

Report MAE and RMSE in percentage points, Spearman rank correlation when defined, interval coverage, and interval width. Intervals are not clipped. Coverage is empirical under substrate-group distribution shift and is not a statistical guarantee for unseen chemistry. The shared fixed amine prevents a claim of strict both-substrates-OOD evaluation.

A single seed validates the pipeline. Scientific model comparisons require repeated seeds, group-level uncertainty, and complete failure reporting. These baselines do not yet demonstrate sequential campaign optimization, prospective discovery, or NVIDIA performance.
