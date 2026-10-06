"""Unit tests for build_user_filter.

These pin the SHAPE of the isolation filter. Whether Qdrant actually enforces
it against real points is an integration test (tests/integration), because the
filter is only as good as the database's behaviour.
"""

from qdrant_client.http import models as qmodels
import pytest

from medrag.retrieval.hybrid_search import build_user_filter


def test_no_user_id_means_curated_only():
    f = build_user_filter(None)
    assert len(f.must) == 2
    assert f.must[0].key == "source"
    assert isinstance(f.must[1], qmodels.IsEmptyCondition)


def test_empty_string_still_builds_a_filter():
    # Fail closed: a falsy-but-not-None id must not silently disable filtering
    # None means curated content only, never unrestricted access.
    assert build_user_filter("") is not None


def test_filter_is_curated_corpus_or_exact_user_match():
    f = build_user_filter("user-123")

    assert isinstance(f, qmodels.Filter)
    # OR semantics: `should`. A `must` here would AND the two conditions and
    # match nothing at all.
    assert f.must is None
    assert f.must_not[0].key == "upload_ready"
    assert len(f.should) == 2

    curated = [c for c in f.should if isinstance(c, qmodels.Filter)][0]
    empties = [c for c in curated.must if isinstance(c, qmodels.IsEmptyCondition)]
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


def test_full_corpus_evaluation_is_explicit_and_excludes_staged_uploads():
    f = build_user_filter(None, full_corpus_evaluation=True)
    assert f.must is None and f.should is None
    assert f.must_not[0].key == "upload_ready"
    assert f.must_not[0].match.value is False


@pytest.mark.parametrize("value", ["true", "false", 1, None])
def test_evaluation_mode_rejects_non_boolean_values(value):
    with pytest.raises(ValueError, match="boolean"):
        build_user_filter(None, full_corpus_evaluation=value)
