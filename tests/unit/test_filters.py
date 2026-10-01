"""Unit tests for build_user_filter.

These pin the SHAPE of the isolation filter. Whether Qdrant actually enforces
it against real points is an integration test (tests/integration), because the
filter is only as good as the database's behaviour.
"""

from qdrant_client.http import models as qmodels

from medrag.retrieval.hybrid_search import build_user_filter


def test_no_user_id_means_no_filter():
    assert build_user_filter(None) is None


def test_empty_string_still_builds_a_filter():
    # Fail closed: a falsy-but-not-None id must not silently disable filtering
    # (only None means "curated corpus, no per-user restriction").
    assert build_user_filter("") is not None


def test_filter_is_curated_corpus_or_exact_user_match():
    f = build_user_filter("user-123")

    assert isinstance(f, qmodels.Filter)
    # OR semantics: `should`. A `must` here would AND the two conditions and
    # match nothing at all.
    assert f.must is None
    assert f.must_not is None
    assert len(f.should) == 2

    empties = [c for c in f.should if isinstance(c, qmodels.IsEmptyCondition)]
    matches = [c for c in f.should if isinstance(c, qmodels.FieldCondition)]
    assert len(empties) == 1 and len(matches) == 1

    # Curated corpus: points with no user_id field at all
    assert empties[0].is_empty.key == "user_id"
    # Uploads: exact match (MatchValue), never substring (MatchText)
    assert matches[0].key == "user_id"
    assert isinstance(matches[0].match, qmodels.MatchValue)
    assert matches[0].match.value == "user-123"


def test_filters_for_different_users_differ():
    assert build_user_filter("user-a") != build_user_filter("user-b")