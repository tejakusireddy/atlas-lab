"""Paired evaluator of the exact released-label engine used by live campaigns."""

import argparse
import csv
import hashlib
import json
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

from atlas_science.baseline import load_snapshot
from atlas_science.decisions import Policy, Predictor, decide
from atlas_science.splits import create_split

POLICIES: tuple[Policy, ...] = ("random", "greedy", "diversity", "ensemble_ucb")


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reference = {
        (r["group_id"], r["seed"], r["count"]): r["best"] for r in rows if r["policy"] == "random"
    }
    summaries = []
    for policy in POLICIES:
        for count in (8, 16, 24, 32, 40, 48):
            groups: dict[str, list[list[float]]] = defaultdict(list)
            for row in rows:
                if row["policy"] == policy and row["count"] == count:
                    groups[row["group_id"]].append(
                        [
                            row["best"],
                            row["regret"],
                            row["best"] - reference[row["group_id"], row["seed"], count],
                        ]
                    )
            means = np.asarray([np.mean(groups[g], axis=0) for g in sorted(groups)])
            if len(means) == 0:
                continue
            rng = np.random.default_rng(42)
            sampled = means[rng.integers(len(means), size=(2000, len(means)))].mean(axis=1)
            result: dict[str, Any] = {"policy": policy, "count": count, "group_count": len(groups)}
            for index, metric in enumerate(
                ("best_observed", "simple_regret", "improvement_over_random")
            ):
                result["mean_" + metric] = float(means[:, index].mean())
                result[metric + "_ci95"] = [
                    float(x) for x in np.quantile(sampled[:, index], [0.025, 0.975])
                ]
            summaries.append(result)
    return summaries


def benchmark(snapshot: Path, output: Path, seeds: list[int], predictor: Predictor) -> None:
    if output.exists():
        raise FileExistsError("Refusing to overwrite evaluation artifacts")
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("Seeds must be nonempty and unique")
    candidates, outcomes = load_snapshot(snapshot)
    split = create_split(candidates, 42)
    campaign_ids = set(split.campaign_ids)
    groups = defaultdict(list)
    for candidate in candidates:
        if candidate.candidate_id in campaign_ids:
            groups[candidate.group_id].append(candidate)

    def observed(cid: str) -> float:
        record = outcomes[cid]
        candidate = by_id[cid]
        if (
            record.qc_state != "PASSED"
            or record.source_kind != "historical_observed"
            or record.observed_yield_pct is None
            or record.source_record_id != candidate.source_record_id
            or record.source_file_sha256 != candidate.source_file_sha256
        ):
            raise ValueError("Evaluator requires source-backed historical measurements")
        return record.observed_yield_pct

    by_id = {c.candidate_id: c for c in candidates}
    output.mkdir(parents=True)
    (output / "models").mkdir()
    rows: list[dict[str, Any]] = []
    with (output / "decisions.jsonl").open("w") as decisions:
        for group_id, pool in sorted(groups.items()):
            optimum = max(observed(c.candidate_id) for c in pool)  # Evaluator only.
            for seed in seeds:
                for policy in POLICIES:
                    selected: list[str] = []
                    labels: dict[str, float] = {}
                    for batch in range(6):
                        decision, model_bytes = decide(
                            pool, selected, labels, policy, predictor, seed + len(selected), 8
                        )
                        if model_bytes is not None:
                            (
                                output
                                / "models"
                                / (decision["model_hash"].removeprefix("sha256:") + ".pkl")
                            ).write_bytes(model_bytes)
                        selected.extend(decision["selected_ids"])
                        assert len(set(selected)) == len(selected) <= 48
                        labels.update({cid: observed(cid) for cid in decision["selected_ids"]})
                        decisions.write(
                            json.dumps(
                                {
                                    "group_id": group_id,
                                    "seed": seed,
                                    "batch": batch + 1,
                                    "decision": decision,
                                },
                                allow_nan=False,
                            )
                            + "\n"
                        )
                        rows.append(
                            {
                                "group_id": group_id,
                                "seed": seed,
                                "policy": policy,
                                "count": len(selected),
                                "best": max(labels.values()),
                                "regret": optimum - max(labels.values()),
                                "selected_ids": json.dumps(selected),
                            }
                        )
            print(f"Completed group {group_id}", flush=True)
    with (output / "trajectories.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (output / "summary.json").write_text(json.dumps(summarize(rows), indent=2) + "\n")
    (output / "split_manifest.json").write_text(split.model_dump_json(indent=2) + "\n")
    manifest = {
        "profile": "campaign-local-released-labels-v1",
        "predictor": predictor,
        "seeds": seeds,
        "budget": 48,
        "initial_batch": 8,
        "split_seed": 42,
        "external_training": None,
        "group_count": len(groups),
        "source_manifest_sha256": hashlib.sha256(
            (snapshot / "source_manifest.json").read_bytes()
        ).hexdigest(),
        "git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "working_tree_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"])),
        "lock_sha256": hashlib.sha256(Path("uv.lock").read_bytes()).hexdigest(),
        "uncertainty": "paired group bootstrap after averaging seeds within group; 2000 resamples",
        "limitations": [
            "Three held-out groups; intervals have limited group-level support",
            "Shared fixed amine; not strict both-substrates OOD",
            "Offline evaluation of live acquisition engine; no robot simulation in this benchmark",
            "No external training labels; not directly comparable to external-training baselines",
            "Predictor ensemble spread is not calibrated confidence",
        ],
        "artifact_hashes": {
            str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(output.rglob("*"))
            if p.is_file()
        },
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=Path("data/snapshots/doyle2018-v1"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=[11, 23, 42, 67, 101])
    parser.add_argument(
        "--predictor", choices=("random_forest", "catboost"), default="random_forest"
    )
    args = parser.parse_args()
    benchmark(args.snapshot, args.output, args.seeds, args.predictor)


if __name__ == "__main__":
    main()
