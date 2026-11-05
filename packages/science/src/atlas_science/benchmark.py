"""Offline sequential evaluator with labels withheld from selection policies."""

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Literal

import numpy as np
from atlas_optimization.selection import random_batch
from numpy.typing import NDArray
from sklearn.ensemble import RandomForestRegressor

from atlas_science.baseline import load_snapshot
from atlas_science.features import FEATURE_VERSION, feature_matrix
from atlas_science.records import Candidate
from atlas_science.splits import create_split

Policy = Literal["random", "diversity", "greedy", "ensemble_ucb"]
POLICIES: tuple[Policy, ...] = ("random", "diversity", "greedy", "ensemble_ucb")


def choose_indices(
    policy: Policy,
    features: NDArray[np.float64],
    selected: list[int],
    observed: NDArray[np.float64],
    train_x: NDArray[np.float64],
    train_y: NDArray[np.float64],
    seed: int,
    count: int = 8,
) -> list[int]:
    """Receives only revealed campaign labels, in exactly selected order."""
    if len(selected) != len(observed) or len(set(selected)) != len(selected):
        raise ValueError("Observed labels must correspond to unique selected candidates")
    if any(index < 0 or index >= len(features) for index in selected):
        raise ValueError("Selection outside candidate pool")
    remaining = sorted(set(range(len(features))) - set(selected))
    if not 0 < count <= len(remaining):
        raise ValueError("Insufficient candidates")
    rng = np.random.default_rng(seed)
    if policy == "random":
        return [int(index) for index in rng.choice(remaining, size=count, replace=False)]
    if policy == "diversity":
        anchors = selected.copy()
        result = []
        for _ in range(count):
            if not anchors:
                index = remaining[0]
            else:
                distances = np.min(
                    np.sum((features[remaining, None] - features[anchors]) ** 2, axis=2), axis=1
                )
                index = remaining[int(np.argmax(distances))]
            result.append(index)
            anchors.append(index)
            remaining.remove(index)
        return result
    if policy not in ("greedy", "ensemble_ucb"):
        raise ValueError("Unknown policy")
    model = RandomForestRegressor(
        n_estimators=64, min_samples_leaf=2, max_features=0.5, random_state=seed, n_jobs=1
    )
    model.fit(np.concatenate([train_x, features[selected]]), np.concatenate([train_y, observed]))
    tree_predictions = np.asarray([tree.predict(features[remaining]) for tree in model.estimators_])
    scores = tree_predictions.mean(axis=0)
    if policy == "ensemble_ucb":
        # Explicit ensemble heuristic, not a calibrated confidence bound.
        scores += tree_predictions.std(axis=0)
    order = sorted(
        range(len(remaining)), key=lambda index: (-float(scores[index]), remaining[index])
    )
    return [remaining[index] for index in order[:count]]


def benchmark(snapshot: Path, output: Path, seeds: list[int], split_seed: int = 42) -> None:
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite benchmark: {output}")
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("Seeds must be nonempty and unique")
    candidates, observations = load_snapshot(snapshot)
    split = create_split(candidates, split_seed)
    by_id = {c.candidate_id: c for c in candidates}
    groups: dict[str, list[Candidate]] = defaultdict(list)
    for candidate_id in split.campaign_ids:
        candidate = by_id[candidate_id]
        groups[candidate.group_id].append(candidate)

    def observed_value(candidate_id: str) -> float:
        observation = observations[candidate_id]
        candidate = by_id[candidate_id]
        if (
            observation.qc_state != "PASSED"
            or observation.source_kind != "historical_observed"
            or observation.observed_yield_pct is None
            or observation.source_file_sha256 != candidate.source_file_sha256
            or observation.source_record_id != candidate.source_record_id
        ):
            raise ValueError("Campaign or training record is not a verified observation")
        return observation.observed_yield_pct

    train_x = feature_matrix([by_id[candidate_id] for candidate_id in split.train_ids])
    train_y = np.asarray([observed_value(candidate_id) for candidate_id in split.train_ids])
    output.mkdir(parents=True)
    (output / "split_manifest.json").write_text(split.model_dump_json(indent=2) + "\n")
    shutil.copyfile(snapshot / "source_manifest.json", output / "source_manifest.json")
    raw_rows: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    for group_id, pool in sorted(groups.items()):
        pool.sort(key=lambda c: c.candidate_id)
        if len(pool) < 48:
            failures.append({"group_id": group_id, "reason": "fewer_than_48_candidates"})
            continue
        ids = [c.candidate_id for c in pool]
        features = feature_matrix(pool)
        # Optimum is evaluator-only and never supplied to choose_indices.
        optimum = max(observed_value(candidate_id) for candidate_id in ids)
        for seed in seeds:
            initial = random_batch(ids, [], 48, 8, seed)
            for policy in POLICIES:
                selected = [ids.index(candidate_id) for candidate_id in initial]
                revealed: list[float] = []
                for batch in range(6):
                    revealed.extend(
                        observed_value(ids[index]) for index in selected[len(revealed) :]
                    )
                    raw_rows.append(
                        {
                            "group_id": group_id,
                            "seed": seed,
                            "policy": policy,
                            "selected_count": len(selected),
                            "best_observed": max(revealed),
                            "simple_regret": optimum - max(revealed),
                            "selected_ids": json.dumps([ids[index] for index in selected]),
                        }
                    )
                    if len(selected) < 48:
                        selected.extend(
                            choose_indices(
                                policy,
                                features,
                                selected,
                                np.asarray(revealed),
                                train_x,
                                train_y,
                                seed + batch,
                            )
                        )
                    if len(selected) > 48 or len(selected) != len(set(selected)):
                        raise AssertionError("Invalid selection returned by policy")
        print(f"Completed group {group_id}", flush=True)
    if not raw_rows:
        raise ValueError("No eligible campaigns")
    with (output / "raw_per_campaign.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(raw_rows[0]))
        writer.writeheader()
        writer.writerows(raw_rows)
    summaries = []
    rng = np.random.default_rng(42)
    for policy in POLICIES:
        for count in (8, 16, 24, 32, 40, 48):
            matching = [
                row
                for row in raw_rows
                if row["policy"] == policy and row["selected_count"] == count
            ]
            # Average paired seeds within group before group-level bootstrap.
            values_by_group: dict[str, list[float]] = defaultdict(list)
            for row in matching:
                values_by_group[str(row["group_id"])].append(float(str(row["best_observed"])))
            means = np.asarray([np.mean(values) for values in values_by_group.values()])
            resamples = rng.choice(means, size=(2000, len(means)), replace=True).mean(axis=1)
            summaries.append(
                {
                    "policy": policy,
                    "selected_count": count,
                    "mean_best_observed": float(means.mean()),
                    "ci_lower": float(np.quantile(resamples, 0.025)),
                    "ci_upper": float(np.quantile(resamples, 0.975)),
                    "group_count": len(means),
                    "seed_count": len(seeds),
                }
            )
    with (output / "metric_summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(summaries[0]))
        writer.writeheader()
        writer.writerows(summaries)
    (output / "failures.jsonl").write_text("".join(json.dumps(f) + "\n" for f in failures))
    manifest = {
        "seeds": seeds,
        "split_seed": split_seed,
        "budget": 48,
        "batch_size": 8,
        "feature_version": FEATURE_VERSION,
        "policies": POLICIES,
        "model": {
            "n_estimators": 64,
            "min_samples_leaf": 2,
            "max_features": 0.5,
            "n_jobs": 1,
            "ucb_std_multiplier": 1,
        },
        "git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "working_tree_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"])),
        "lock_sha256": hashlib.sha256(Path("uv.lock").read_bytes()).hexdigest(),
        "limitations": [
            "Offline evaluation only; no protocol simulation performed",
            "Three held-out campaign groups, not a ten-group study",
            "Shared fixed amine; not strict both-substrates-OOD",
            "Ensemble spread is an uncalibrated acquisition heuristic",
            "Group-bootstrap intervals are limited by small group count",
        ],
        "artifact_hashes": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(output.iterdir())
            if p.is_file()
        },
    }
    (output / "run_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=Path("data/snapshots/doyle2018-v1"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2, 3, 4])
    parser.add_argument("--split-seed", type=int, default=42)
    args = parser.parse_args()
    benchmark(args.snapshot, args.output, args.seeds, args.split_seed)


if __name__ == "__main__":
    main()
