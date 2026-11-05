"""Deterministic acquisition from explicit eligible labels; no dataset or oracle I/O."""

import hashlib
import pickle
from typing import Any, Literal, cast

import numpy as np
import sklearn
from atlas_domain.hashing import JSONValue, content_hash
from atlas_optimization.selection import eligible_ids, random_batch
from catboost import CatBoostRegressor
from sklearn.ensemble import RandomForestRegressor

from atlas_science.features import FEATURE_VERSION, feature_matrix
from atlas_science.records import Candidate

Policy = Literal["random", "greedy", "diversity", "ensemble_ucb"]
Predictor = Literal["random_forest", "catboost"]
VERSION = "released-acquisition-v1"


def decide(
    candidates: list[Candidate],
    selected: list[str],
    labels: dict[str, float],
    policy: Policy,
    predictor: Predictor,
    seed: int,
    count: int,
    budget: int = 48,
) -> tuple[dict[str, Any], bytes | None]:
    """Labels must be preauthorized by the caller; unknown and unselected IDs fail closed."""
    if policy not in ("random", "greedy", "diversity", "ensemble_ucb"):
        raise ValueError("Unknown acquisition policy")
    if predictor not in ("random_forest", "catboost"):
        raise ValueError("Unknown predictor")
    ordered = sorted(candidates, key=lambda c: c.candidate_id)
    ids = [c.candidate_id for c in ordered]
    if not set(labels).issubset(selected):
        raise ValueError("Training labels must belong to released selected candidates")
    if any(not np.isfinite(value) or not 0 <= value <= 100 for value in labels.values()):
        raise ValueError("Only finite percentage labels are eligible")
    if count:
        remaining = eligible_ids(ids, selected, budget, count)
    else:
        if (
            len(set(ids)) != len(ids)
            or len(set(selected)) != len(selected)
            or not set(selected) <= set(ids)
        ):
            raise ValueError("Invalid selected candidate pool")
        remaining = sorted(set(ids) - set(selected))
    decision: dict[str, Any] = {
        "version": VERSION,
        "policy": policy,
        "predictor": predictor,
        "seed": seed,
        "feature_version": FEATURE_VERSION,
        "candidate_pool_hash": content_hash(cast(JSONValue, ids)),
        "excluded_candidate_ids": sorted(selected),
        "training_candidate_ids": sorted(labels),
        "training_data_hash": content_hash(cast(JSONValue, labels)),
        "model_hash": None,
        "model_parameters": None,
        "feature_hash": None,
        "scores": [],
        "selected_ids": [],
        "uncertainty_kind": None,
        "fallback_reason": None,
    }
    if not selected or policy == "random":
        chosen = random_batch(ids, selected, budget, count, seed) if count else []
        decision.update(
            selected_ids=chosen, fallback_reason="shared_initial_design" if not selected else None
        )
        return decision, None
    x = feature_matrix(ordered)
    decision["feature_hash"] = "sha256:" + hashlib.sha256(x.astype("<f8").tobytes()).hexdigest()
    position = {cid: index for index, cid in enumerate(ids)}
    indices = [position[cid] for cid in remaining]
    mean = np.zeros(len(remaining))
    spread = np.zeros(len(remaining))
    artifact = None
    if policy in ("greedy", "ensemble_ucb"):
        if not labels:
            decision.update(
                selected_ids=random_batch(ids, selected, budget, count, seed) if count else [],
                fallback_reason="no_eligible_released_labels",
            )
            return decision, None
        training_ids = sorted(labels)
        tx = x[[position[cid] for cid in training_ids]]
        ty = np.asarray([labels[cid] for cid in training_ids])
        if predictor == "random_forest":
            parameters = {
                "n_estimators": 64,
                "min_samples_leaf": 2,
                "max_features": 0.5,
                "random_state": seed,
                "n_jobs": 1,
            }
            model = RandomForestRegressor(**parameters)
            model.fit(tx, ty)
            predictions = (
                np.asarray([tree.predict(x[indices]) for tree in model.estimators_])
                if indices
                else np.empty((64, 0))
            )
            artifact = pickle.dumps(model, protocol=5)
            decision["library_version"] = sklearn.__version__
            decision["uncertainty_kind"] = "uncalibrated_tree_spread"
        else:
            import catboost

            parameters = {
                "iterations": 100,
                "depth": 4,
                "learning_rate": 0.05,
                "thread_count": 1,
                "verbose": False,
                "allow_writing_files": False,
                "allow_const_label": True,
                "random_seed": seed,
            }
            models = []
            for offset in range(5):
                fitted = CatBoostRegressor(**(parameters | {"random_seed": seed + offset}))
                fitted.fit(tx, ty)
                models.append(fitted)
            predictions = (
                np.asarray([m.predict(x[indices]) for m in models]) if indices else np.empty((5, 0))
            )
            artifact = pickle.dumps(models, protocol=5)
            decision["library_version"] = catboost.__version__
            decision["uncertainty_kind"] = "uncalibrated_seed_ensemble_spread"
            parameters["ensemble_size"] = 5
        mean, spread = predictions.mean(axis=0), predictions.std(axis=0)
        decision["model_parameters"] = parameters
        decision["model_hash"] = "sha256:" + hashlib.sha256(artifact).hexdigest()
    if policy == "diversity":
        anchors = [position[cid] for cid in selected]
        available = remaining.copy()
        chosen = []
        scores: list[dict[str, Any]] = []
        for step in range(count):
            distances = {
                cid: float(np.min(np.sum((x[position[cid]] - x[anchors]) ** 2, axis=1)))
                for cid in available
            }
            winner = min(available, key=lambda cid: (-distances[cid], cid))
            scores.extend(
                {
                    "candidate_id": cid,
                    "step": step,
                    "score": distances[cid],
                    "rank": rank + 1,
                    "selected": cid == winner,
                }
                for rank, cid in enumerate(
                    sorted(available, key=lambda cid: (-distances[cid], cid))
                )
            )
            chosen.append(winner)
            anchors.append(position[winner])
            available.remove(winner)
        decision.update(scores=scores, selected_ids=chosen)
    else:
        values = mean + spread if policy == "ensemble_ucb" else mean
        rank = sorted(range(len(remaining)), key=lambda i: (-float(values[i]), remaining[i]))
        chosen = [remaining[i] for i in rank[:count]]
        decision.update(
            selected_ids=chosen,
            scores=[
                {
                    "candidate_id": remaining[i],
                    "prediction": float(mean[i]),
                    "uncertainty": float(spread[i]),
                    "score": float(values[i]),
                    "rank": order + 1,
                    "selected": remaining[i] in chosen,
                }
                for order, i in enumerate(rank)
            ],
        )
    return decision, artifact
