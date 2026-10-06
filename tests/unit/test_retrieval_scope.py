"""The reranking wrapper must preserve the retrieval privacy boundary."""
from unittest.mock import Mock

import pytest

from medrag.retrieval import reranking


@pytest.mark.parametrize("scope", [{}, {"user_id": "session-a"}, {"full_corpus_evaluation": True}])
def test_reranking_forwards_scope(monkeypatch, scope):
    search = Mock(return_value=[])
    monkeypatch.setattr(reranking, "hybrid_search", search)
    assert reranking.search_with_reranking(object(), "query", **scope) == []
    assert search.call_args.kwargs["user_id"] == scope.get("user_id")
    assert search.call_args.kwargs["full_corpus_evaluation"] is scope.get("full_corpus_evaluation", False)
