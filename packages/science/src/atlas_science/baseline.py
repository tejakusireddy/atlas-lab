"""Offline evaluator for frozen CPU predictive baselines; never a planner tool."""

import argparse
import csv
import hashlib
import importlib.metadata
import json
import math
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

import joblib
import mlflow
import numpy as np
from catboost import CatBoostRegressor
from numpy.typing import NDArray
from scipy.stats import spearmanr
from sklearn.ensemble import RandomForestRegressor

from atlas_science.features import FEATURE_VERSION, feature_matrix
from atlas_science.records import Candidate, Observation
from atlas_science.splits import create_split


def load_snapshot(snapshot: Path) -> tuple[list[Candidate], dict[str, Observation]]:
    manifest = json.loads((snapshot / "source_manifest.json").read_text())
    for name, expected in manifest["artifact_hashes"].items():
        path = (snapshot / name).resolve()
        if not path.is_relative_to(snapshot.resolve()):
            raise ValueError("Artifact path escapes snapshot")
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError(f"Snapshot artifact changed: {name}")
    candidates = [
        Candidate.model_validate_json(line)
        for line in (snapshot / "candidates.jsonl").read_text().splitlines()
    ]
    observations = [
        Observation.model_validate_json(line)
        for line in (snapshot / "oracle/observations.jsonl").read_text().splitlines()
    ]
    by_id = {o.candidate_id: o for o in observations}
    if len(by_id) != len(observations) or len({c.candidate_id for c in candidates}) != len(
        candidates
    ):
        raise ValueError("Duplicate snapshot record")
    return candidates, by_id


def regression_metrics(
    actual: NDArray[np.float64], predicted: NDArray[np.float64], radius: float
) -> dict[str, float]:
    if actual.shape != predicted.shape or actual.size < 2:
        raise ValueError("Metrics require matched arrays with at least two observations")
    if not np.isfinite(actual).all() or not np.isfinite(predicted).all():
        raise ValueError("Nonfinite metric inputs")
    difference = actual - predicted
    metrics = {
        "mae_pct_points": float(np.abs(difference).mean()),
        "rmse_pct_points": float(np.sqrt(np.mean(difference**2))),
        "interval_coverage": float(np.mean(np.abs(difference) <= radius)),
        "interval_width_pct_points": 2 * radius,
    }
    if np.ptp(actual) > 0 and np.ptp(predicted) > 0:
        metrics["spearman"] = float(spearmanr(actual, predicted).statistic)
    return metrics


def calibration_radius(
    actual: NDArray[np.float64], predicted: NDArray[np.float64], coverage: float = 0.9
) -> float:
    if actual.shape != predicted.shape or not len(actual) or not 0 < coverage < 1:
        raise ValueError("Invalid calibration inputs")
    residuals = np.abs(actual - predicted)
    if not np.isfinite(residuals).all():
        raise ValueError("Nonfinite calibration residual")
    rank = min(len(residuals), math.ceil((len(residuals) + 1) * coverage))
    return float(np.sort(residuals)[rank - 1])


def make_model(name: str, seed: int) -> Any:
    if name == "random_forest":
        return RandomForestRegressor(
            n_estimators=128, min_samples_leaf=2, max_features=0.5, n_jobs=1, random_state=seed
        )
    if name == "catboost":
        return CatBoostRegressor(
            iterations=300,
            depth=6,
            learning_rate=0.05,
            loss_function="RMSE",
            random_seed=seed,
            thread_count=1,
            verbose=False,
            allow_writing_files=False,
        )
    raise ValueError(f"Unknown model: {name}")


def run_baseline(snapshot: Path, output: Path, seed: int, tracking_uri: str) -> dict[str, object]:
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite evaluation: {output}")
    candidates, observations = load_snapshot(snapshot)
    split = create_split(candidates, seed)
    by_id = {c.candidate_id: c for c in candidates}

    def partition(ids: tuple[str, ...]) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        eligible = []
        labels = []
        for candidate_id in ids:
            observation = observations.get(candidate_id)
            if (
                observation is None
                or observation.qc_state != "PASSED"
                or observation.source_kind != "historical_observed"
                or observation.observed_yield_pct is None
            ):
                raise ValueError("Frozen baseline partition has ineligible observations")
            candidate = by_id[candidate_id]
            if (
                candidate.source_record_id != observation.source_record_id
                or candidate.source_file_sha256 != observation.source_file_sha256
            ):
                raise ValueError("Observation provenance mismatch")
            eligible.append(candidate)
            labels.append(observation.observed_yield_pct)
        return feature_matrix(eligible), np.asarray(labels, dtype=np.float64)

    # Campaign labels are never read by this predictive baseline.
    train_x, train_y = partition(split.train_ids)
    calibration_x, calibration_y = partition(split.calibration_ids)
    test_x, test_y = partition(split.ood_test_ids)
    output.mkdir(parents=True)
    (output / "split_manifest.json").write_text(split.model_dump_json(indent=2) + "\n")
    shutil.copyfile(snapshot / "source_manifest.json", output / "source_manifest.json")
    mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment("atlas-cpu-baselines")
    results: dict[str, object] = {}
    for name in ("random_forest", "catboost"):
        model = make_model(name, seed)
        model.fit(train_x, train_y)
        radius = calibration_radius(calibration_y, np.asarray(model.predict(calibration_x)))
        predictions = np.asarray(model.predict(test_x), dtype=np.float64)
        metrics = regression_metrics(test_y, predictions, radius)
        model_path = output / f"{name}.joblib"
        joblib.dump(model, model_path)
        with (output / f"{name}_predictions.csv").open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "candidate_id",
                    "observed_yield_pct",
                    "predicted_yield_pct",
                    "interval_lower",
                    "interval_upper",
                ]
            )
            for candidate_id, actual, predicted in zip(
                split.ood_test_ids, test_y, predictions, strict=True
            ):
                writer.writerow(
                    [candidate_id, actual, predicted, predicted - radius, predicted + radius]
                )
        with mlflow.start_run(run_name=f"{name}-seed-{seed}") as run:
            mlflow.log_params(
                {
                    "seed": seed,
                    "feature_version": FEATURE_VERSION,
                    "train_count": len(train_y),
                    "calibration_count": len(calibration_y),
                    "test_count": len(test_y),
                    "model_config": json.dumps(model.get_params()),
                }
            )
            mlflow.log_metrics(metrics)
            mlflow.log_artifact(str(model_path))
            mlflow.log_artifact(str(output / "split_manifest.json"))
            results[name] = {
                "metrics": metrics,
                "calibration_radius": radius,
                "model_config": model.get_params(),
                "mlflow_run_id": run.info.run_id,
            }
    manifest = {
        "seed": seed,
        "feature_version": FEATURE_VERSION,
        "git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "working_tree_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"])),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "versions": {
            name: importlib.metadata.version(name)
            for name in ["rdkit", "numpy", "scikit-learn", "catboost", "mlflow-skinny"]
        },
        "lock_sha256": hashlib.sha256(Path("uv.lock").read_bytes()).hexdigest(),
        "results": results,
        "limitations": [
            "Pair-held-out, not strict both-substrates-OOD",
            "Calibration coverage is empirical under group distribution shift",
            "Single seed is an engineering smoke run, not a comparative study",
        ],
        "artifact_hashes": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(output.iterdir())
            if p.is_file()
        },
    }
    (output / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=Path("data/snapshots/doyle2018-v1"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--tracking-uri", default="sqlite:///artifacts/mlflow.db")
    args = parser.parse_args()
    print(
        json.dumps(run_baseline(args.snapshot, args.output, args.seed, args.tracking_uri), indent=2)
    )


if __name__ == "__main__":
    main()
