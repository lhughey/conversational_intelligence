"""Cluster bootstrap: correctness, determinism, and the edge cases that
must not crash a benchmark run."""

import random

import pytest

from convint.bench.stats import cluster_bootstrap_ci, format_ci, rate_summary


def test_point_is_the_pooled_mean_not_the_mean_of_cluster_means():
    # cluster a: 3/4, cluster b: 0/1 -> pooled 3/5, not (0.75 + 0) / 2
    point, lo, hi = cluster_bootstrap_ci({"a": [1, 1, 1, 0], "b": [0]})
    assert point == pytest.approx(0.6)
    assert lo is not None and hi is not None


def test_known_two_cluster_example_bounds():
    # Two clusters, all-ones and all-zeros: each resample is {a,a}, {a,b} or
    # {b,b}, so the bootstrap distribution lives on {0, 0.5, 1} and the 95%
    # percentile interval spans the full range.
    point, lo, hi = cluster_bootstrap_ci({"a": [1, 1], "b": [0, 0]})
    assert point == 0.5
    assert lo == 0.0 and hi == 1.0


def test_flat_values_with_cluster_ids_match_the_mapping_form():
    values = [1, 0, 1, 1, 0, 0, 1]
    ids = ["x", "x", "y", "y", "z", "z", "z"]
    mapping = {"x": [1, 0], "y": [1, 1], "z": [0, 0, 1]}
    assert cluster_bootstrap_ci(values, ids) == cluster_bootstrap_ci(mapping)


def test_same_seed_same_interval_different_seed_may_differ():
    rng = random.Random(42)
    data = {f"c{i}": [rng.random() < 0.6 for _ in range(rng.randint(2, 9))] for i in range(12)}
    assert cluster_bootstrap_ci(data, seed=7) == cluster_bootstrap_ci(data, seed=7)
    assert cluster_bootstrap_ci(data, seed=7) != cluster_bootstrap_ci(data, seed=8)


def test_interval_contains_the_point():
    rng = random.Random(3)
    for _ in range(20):
        data = {f"c{i}": [rng.random() < 0.7 for _ in range(rng.randint(1, 8))]
                for i in range(rng.randint(3, 15))}
        point, lo, hi = cluster_bootstrap_ci(data)
        assert lo <= point <= hi
        assert 0.0 <= lo <= hi <= 1.0


def test_clustering_widens_the_interval_versus_treating_items_as_independent():
    """The reason this module exists: correlated items are not independent."""
    # Ten clusters, each internally identical (perfectly correlated).
    data = {f"c{i}": [i % 2] * 10 for i in range(10)}
    flat = [v for vs in data.values() for v in vs]
    _, c_lo, c_hi = cluster_bootstrap_ci(data)
    _, i_lo, i_hi = cluster_bootstrap_ci(flat, list(range(len(flat))))
    assert (c_hi - c_lo) > (i_hi - i_lo)


def test_custom_stat_is_applied_to_pooled_values():
    point, lo, hi = cluster_bootstrap_ci({"a": [1, 5], "b": [3]}, stat=max)
    assert point == 5
    assert lo >= 3 and hi == 5


def test_empty_input_is_none_not_a_crash():
    assert cluster_bootstrap_ci([], []) == (None, None, None)
    assert cluster_bootstrap_ci({}) == (None, None, None)
    assert cluster_bootstrap_ci({"a": []}) == (None, None, None)


def test_single_cluster_gives_a_point_and_no_interval():
    # A one-cluster bootstrap would print a zero-width interval: false certainty.
    assert cluster_bootstrap_ci({"only": [1, 0, 1, 1]}) == (0.75, None, None)
    # empty clusters do not count toward k
    assert cluster_bootstrap_ci({"only": [1, 0], "empty": []}) == (0.5, None, None)


def test_mismatched_lengths_and_missing_ids_are_rejected():
    with pytest.raises(ValueError):
        cluster_bootstrap_ci([1, 0], ["a"])
    with pytest.raises(TypeError):
        cluster_bootstrap_ci([1, 0])


def test_rate_summary_reports_n_and_k_and_handles_zero_denominator():
    s = rate_summary([1, 0, 1], ["a", "a", "b"])
    assert s["n"] == 3 and s["k"] == 2
    assert s["rate"] == pytest.approx(2 / 3)
    assert len(s["ci"]) == 2
    assert rate_summary([], []) == {"rate": None, "ci": None, "n": 0, "k": 0}


def test_format_ci():
    assert format_ci(0.77, [0.68, 0.85], 92, 11) == "77% [68–85] n=92 (k=11 transcripts)"
    assert format_ci(0.77, [0.68, 0.85]) == "77% [68–85]"
    assert format_ci(1.0, None) == "100% [—]"
    assert format_ci(None) == "n/a"
