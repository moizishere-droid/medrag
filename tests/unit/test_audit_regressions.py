"""Regression checks for ingestion and saved-evidence integrity."""
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
import requests

from medrag.embeddings import embedder, storage
from medrag.ingestion import pubmed_client, openfda_client
from medrag.processing.chunker import token_windows


def test_embedding_response_is_aligned_by_index():
    client = SimpleNamespace(embeddings=SimpleNamespace(create=Mock(return_value=SimpleNamespace(data=[
        SimpleNamespace(index=1, embedding=[2.0]), SimpleNamespace(index=0, embedding=[1.0]),
    ]))))
    assert embedder.embed_batch_with_retry(client, ["first", "second"], max_retries=1) == [[1.0], [2.0]]


def test_incomplete_embedding_response_cannot_silently_drop_chunks():
    client = SimpleNamespace(embeddings=SimpleNamespace(create=Mock(return_value=SimpleNamespace(data=[]))))
    with pytest.raises(ValueError, match="count"):
        embedder.embed_batch_with_retry(client, ["first"], max_retries=1)


@pytest.mark.parametrize("vectors,rows", [(np.zeros((2, 3)), [1]), (np.array([[np.nan]]), [1]), (np.zeros(3), [1])])
def test_storage_rejects_invalid_alignment(vectors, rows):
    with pytest.raises(ValueError):
        storage.validate_alignment(vectors, rows, "test")


def test_unicode_window_split_preserves_every_character():
    text = "اردو 中文 💊 café " * 40
    windows = token_windows(text, 9)
    assert "".join(windows) == text
    assert all(len(embedder.ENCODING.encode(window)) <= 9 for window in windows)


def test_pubmed_search_closes_handle_and_filters_language(monkeypatch):
    handle = Mock()
    handle.__enter__ = Mock(return_value=handle)
    handle.__exit__ = Mock(return_value=False)
    search = Mock(return_value=handle)
    monkeypatch.setattr(pubmed_client.Entrez, "esearch", search)
    monkeypatch.setattr(pubmed_client.Entrez, "read", lambda _: {"IdList": ["123"]})
    assert pubmed_client.search_pubmed("asthma") == ["123"]
    assert search.call_args.kwargs["term"] == "(asthma) AND english[Language]"
    handle.__exit__.assert_called_once()


def test_empty_pubmed_fetch_never_calls_network(monkeypatch):
    fetch = Mock()
    monkeypatch.setattr(pubmed_client.Entrez, "efetch", fetch)
    assert pubmed_client.fetch_articles_raw([]) == {"PubmedArticle": []}
    fetch.assert_not_called()


def test_openfda_server_failure_is_not_an_empty_success(monkeypatch):
    response = Mock(status_code=503)
    response.raise_for_status.side_effect = requests.HTTPError("service unavailable")
    monkeypatch.setattr(openfda_client.requests, "get", lambda *a, **k: response)
    with pytest.raises(requests.HTTPError):
        openfda_client.fetch_drugs_raw("asthma", max_retries=1)


def test_openfda_missing_identity_is_a_clear_parse_error():
    with pytest.raises(ValueError, match="cannot identify"):
        openfda_client.parse_drug_record({"openfda": {"brand_name": [], "generic_name": []}}, "asthma")


def test_pubmed_storage_is_idempotent_across_repeated_batches(tmp_path):
    from medrag.ingestion.models import Article
    from medrag.ingestion.storage import save_articles, load_articles
    article = Article(pmid="123", title="Title", abstract="Text", authors=[], journal="Journal", pub_date="2026", language="eng", topic="asthma", url="https://pubmed.ncbi.nlm.nih.gov/123/")
    save_articles([article, article], "asthma", str(tmp_path))
    save_articles([article], "asthma", str(tmp_path))
    assert [a.pmid for a in load_articles("asthma", str(tmp_path))] == ["123"]


@pytest.mark.parametrize("full_corpus", [False, True])
def test_evaluation_generates_from_the_exact_scored_evidence(monkeypatch, full_corpus):
    from medrag.evaluation.evaluation import run_pipeline_on_test_set
    from medrag.retrieval import reranking
    from medrag.generation import generation
    results = [{"payload": {"raw_text": "Evidence"}}]
    search = Mock(return_value=results)
    generate = Mock(return_value="Answer [1]")
    monkeypatch.setattr(reranking, "search_with_reranking", search)
    monkeypatch.setattr(generation, "generate_answer", generate)
    records = run_pipeline_on_test_set([{"question": "Q?", "ground_truth": "Reference"}], object(), object(), candidate_pool_size=7, top_n=2, full_corpus_evaluation=full_corpus)
    search.assert_called_once()
    assert search.call_args.kwargs["full_corpus_evaluation"] is full_corpus
    assert generate.call_args.kwargs["results"] is results
    assert generate.call_args.kwargs["top_n"] == 2
    assert records[0]["contexts"] == ["Evidence"]
