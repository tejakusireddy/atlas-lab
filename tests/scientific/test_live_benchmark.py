from atlas_science.live_benchmark import summarize


def test_paired_group_summary_keeps_comparisons_paired() -> None:
    rows = []
    for group, base in [("a", 20.0), ("b", 60.0)]:
        for seed in (1, 2):
            for policy, delta in [("random", 0.0), ("greedy", 5.0)]:
                rows.append(
                    {
                        "group_id": group,
                        "seed": seed,
                        "policy": policy,
                        "count": 48,
                        "best": base + delta,
                        "regret": 100 - base - delta,
                    }
                )
    results = summarize(rows)
    greedy = next(r for r in results if r["policy"] == "greedy")
    assert greedy["mean_best_observed"] == 45
    assert greedy["mean_simple_regret"] == 55
    assert greedy["mean_improvement_over_random"] == 5
    assert greedy["improvement_over_random_ci95"] == [5, 5]
