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


def test_expanded_cohort_preserves_the_predictive_test_partition() -> None:
    from atlas_science.live_benchmark import cohort_ids
    from atlas_science.splits import create_split

    from tests.scientific.test_splits import candidates

    records = candidates()
    split = create_split(records)
    expanded = cohort_ids(records, "exploratory_development")
    assert expanded == set(split.train_ids + split.calibration_ids + split.campaign_ids)
    assert not expanded.intersection(split.ood_test_ids)
    assert cohort_ids(records, "original_campaign") == set(split.campaign_ids)
    assert len(expanded) > len(split.campaign_ids)
