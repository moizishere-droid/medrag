"""Unit tests for reciprocal_rank_fusion.

Expected values are computed by hand from the RRF definition

    score(d) = sum over lists of 1 / (k + rank_of_d_in_list)      (rank starts at 1)

so the tests check the math independently of the implementation.
"""

import pytest

from medrag.retrieval.hybrid_search import DEFAULT_RRF_K, reciprocal_rank_fusion


def scores(ranked):
    return dict(ranked)


def order(ranked):
    return [chunk_id for chunk_id, _ in ranked]


def test_default_k_is_60():
    # Deliberate Phase 10 decision: Qdrant's native fusion uses k=1; we use the
    # standard k=60 from the original RRF paper. Guard against silent changes.
    assert DEFAULT_RRF_K == 60


def test_default_k_matches_explicit_60(make_points):
    lists = [make_points("a", "b"), make_points("b", "a")]
    assert reciprocal_rank_fusion(lists) == reciprocal_rank_fusion(lists, k=60)


def test_single_list_scores_follow_formula(make_points):
    ranked, _ = reciprocal_rank_fusion([make_points("a", "b", "c")], k=60)
    s = scores(ranked)
    assert s["a"] == pytest.approx(1 / 61)  # rank 1, not rank 0
    assert s["b"] == pytest.approx(1 / 62)
    assert s["c"] == pytest.approx(1 / 63)
    assert order(ranked) == ["a", "b", "c"]


def test_chunk_in_both_lists_sums_contributions(make_points):
    dense = make_points("a", "b", "c")
    sparse = make_points("b", "c", "d")
    ranked, _ = reciprocal_rank_fusion([dense, sparse], k=60)
    s = scores(ranked)
    assert s["a"] == pytest.approx(1 / 61)  # dense rank 1 only
    assert s["b"] == pytest.approx(1 / 62 + 1 / 61)  # dense 2, sparse 1
    assert s["c"] == pytest.approx(1 / 63 + 1 / 62)  # dense 3, sparse 2
    assert s["d"] == pytest.approx(1 / 63)  # sparse rank 3 only
    assert order(ranked) == ["b", "c", "a", "d"]


def test_k_controls_how_much_a_single_top_rank_dominates(make_points):
    """A is #1 in one list only; B is #4 in both lists.

    k=60 (standard): agreement across signals beats a lone #1  -> B above A.
    k=1  (Qdrant native fusion): a lone #1 wins                -> A above B.
    This is the behavioural difference that motivated hand-implementing RRF.
    """
    dense = make_points("A", "p", "q", "B")
    sparse = make_points("r", "s", "t", "B")

    s60 = scores(reciprocal_rank_fusion([dense, sparse], k=60)[0])
    assert s60["A"] == pytest.approx(1 / 61)
    assert s60["B"] == pytest.approx(2 / 64)
    assert s60["B"] > s60["A"]

    s1 = scores(reciprocal_rank_fusion([dense, sparse], k=1)[0])
    assert s1["A"] == pytest.approx(1 / 2)
    assert s1["B"] == pytest.approx(2 / 5)
    assert s1["A"] > s1["B"]


def test_output_is_sorted_descending_by_score(make_points):
    ranked, _ = reciprocal_rank_fusion(
        [make_points("a", "b", "c", "d"), make_points("d", "c", "b", "a")]
    )
    values = [score for _, score in ranked]
    assert values == sorted(values, reverse=True)


def test_empty_input_returns_empty_results():
    assert reciprocal_rank_fusion([]) == ([], {})
    assert reciprocal_rank_fusion([[], []]) == ([], {})


def test_one_empty_signal_degrades_to_the_other(make_points):
    # e.g. the sparse query returns nothing for an all-stopword query
    ranked, _ = reciprocal_rank_fusion([make_points("a", "b"), []], k=60)
    assert order(ranked) == ["a", "b"]
    assert scores(ranked)["a"] == pytest.approx(1 / 61)


def test_payload_map_covers_every_chunk_from_both_lists(make_points):
    _, payloads = reciprocal_rank_fusion([make_points("a", "b"), make_points("b", "c")])
    assert set(payloads) == {"a", "b", "c"}
    assert payloads["c"]["chunk_id"] == "c"