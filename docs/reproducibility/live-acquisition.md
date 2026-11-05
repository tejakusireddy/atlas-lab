# Released-observation acquisition

The `released-acquisition-v1` engine accepts outcome-free candidates, reserved IDs, and an explicit mapping of eligible released yields. It performs no dataset-file or oracle access. Unknown/unselected label IDs and invalid percentage values are rejected. Every strategy shares the same seeded-random initial design.

Supported policies are random, greedy predicted yield, sequential farthest-point diversity, and ensemble UCB (mean plus one ensemble standard deviation). Ties resolve by candidate ID. Diversity records each within-batch step, because adding an anchor changes remaining scores.

Random Forest uses 64 trees, minimum leaf size two, half the features per split, and one thread. CatBoost uses five separately seeded models with 100 iterations, depth four, learning rate 0.05, one thread, and no output files. Tree/seed ensemble spread is an uncalibrated acquisition heuristic, not a confidence interval. Both models use role-separated Morgan features.

Decision artifacts record training candidate IDs and values through a training-data hash, feature version and matrix hash, pool hash, effective seed, model parameters and library version, predictions, spread, scores, ranks, and selected IDs. Serialized model bytes have their own SHA-256 digest. CatBoost serialization may include run-specific metadata; scientific reproducibility is assessed using predictions and selected trajectories, not identical serialized bytes.

With no eligible labels, model-guided policies fall back explicitly to seeded random. This first profile trains only on released observations within the campaign. No external labels are enabled; adding external training requires a separately verified, disjoint training partition and provenance contract.
