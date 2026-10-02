"""Unit tests for answer generation (Phase 14).

Retrieval, OpenAI and Neo4j are all faked. These tests check OUR logic: how
context is formatted, how graph facts are curated, and how the prompt is
assembled. They say nothing about answer quality (that is Phase 17's RAGAS job).
"""

import importlib
from types import SimpleNamespace

import pytest

from medrag.citations.citations import build_citations

gen = importlib.import_module("medrag.generation.generation")


@pytest.fixture(autouse=True)
def reset_drug_cache(monkeypatch):
    """get_all_known_drug_names caches at module level; reset it per test."""
    monkeypatch.setattr(gen, "_known_drug_names_cache", None)


def make_result(i, source="pubmed", **extra):
    payload = {
        "chunk_id": f"c{i}",
        "source": source,
        "source_id": str(100 + i),
        "raw_text": f"raw text {i}",
        "metadata": {"title": f"Title {i}"},
    }
    payload.update(extra)
    return {"payload": payload}


def fact(relationship, disease, drug="Metformin"):
    return {"drug": drug, "relationship": relationship, "disease": disease}


# --------------------------------------------------------------------------
# format_context
# --------------------------------------------------------------------------
def test_format_context_numbers_blocks_from_one_and_labels_the_source():
    out = gen.format_context([make_result(1, "pubmed"), make_result(2, "who")])
    assert out == "[1] (source: pubmed)\nraw text 1\n\n[2] (source: who)\nraw text 2"


def test_format_context_of_nothing_is_empty():
    assert gen.format_context([]) == ""


def test_contract_context_numbering_matches_citation_resolution():
    """CONTRACT with citations.py: the model is told '[k]' is results[k-1], and
    build_citations resolves '[k]' back to results[k-1]. If either side shifts
    its numbering, every citation silently points at the wrong source."""
    results = [make_result(1), make_result(2), make_result(3)]
    context = gen.format_context(results)

    for k in (1, 2, 3):
        assert f"[{k}] (source: pubmed)\nraw text {k}" in context
        (citation,) = build_citations(f"claim [{k}]", results, {})
        assert citation["chunk_id"] == f"c{k}"


# --------------------------------------------------------------------------
# find_mentioned_drug
# --------------------------------------------------------------------------
def test_mentioned_drug_is_matched_case_insensitively():
    assert gen.find_mentioned_drug("Side effects of METFORMIN?", ["Metformin", "Aspirin"]) == "Metformin"


def test_no_known_drug_in_query_returns_none():
    assert gen.find_mentioned_drug("What is hypertension?", ["Metformin"]) is None
    assert gen.find_mentioned_drug("anything", []) is None


def test_first_match_in_list_order_wins():
    """Characterization: there is no longest-match rule. With both 'insulin' and
    'insulin glargine' known, whichever comes first in the list is returned."""
    names = ["insulin", "insulin glargine"]
    assert gen.find_mentioned_drug("dosing for insulin glargine", names) == "insulin"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECT (substring match, no word boundary): 'environmental' contains "
        "'iron', so a query that never mentions the drug pulls in its graph facts. "
        "Fix: match on word boundaries (regex \\b) and prefer the longest name, "
        "then drop this marker."
    ),
)
def test_drug_name_inside_another_word_is_not_a_mention():
    assert gen.find_mentioned_drug("environmental exposure risks", ["iron"]) is None


# --------------------------------------------------------------------------
# Fake Neo4j driver
# --------------------------------------------------------------------------
class FakeSession:
    def __init__(self, rows, log):
        self._rows, self._log = rows, log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def run(self, query, **params):
        self._log.append((query, params))
        return iter(self._rows)


class FakeDriver:
    def __init__(self, rows=()):
        self.rows, self.log = list(rows), []

    def session(self):
        return FakeSession(self.rows, self.log)


def test_known_drug_names_are_read_from_the_graph_and_cached():
    first = FakeDriver([{"name": "Metformin"}, {"name": "Lisinopril"}])
    assert gen.get_all_known_drug_names(first) == ["Metformin", "Lisinopril"]

    second = FakeDriver([{"name": "Different"}])
    assert gen.get_all_known_drug_names(second) == ["Metformin", "Lisinopril"]  # cached
    assert second.log == []  # never queried

    assert gen.get_all_known_drug_names(second, use_cache=False) == ["Different"]


def test_graph_facts_query_uses_the_normalised_name():
    rows = [fact("TREATS", "type 2 diabetes mellitus")]
    driver = FakeDriver(rows)

    out = gen.get_graph_facts_for_drug(driver, "  Metformin ")

    assert out == rows
    ((_query, params),) = driver.log
    assert params == {"name": "metformin"}  # stripped and lowercased


# --------------------------------------------------------------------------
# get_graph_facts_for_drug_curated
# --------------------------------------------------------------------------
@pytest.fixture
def stub_graph_facts(monkeypatch):
    def _install(facts):
        monkeypatch.setattr(gen, "get_graph_facts_for_drug", lambda driver, drug: list(facts))

    return _install


def test_disease_under_both_treats_and_causes_is_dropped_from_causes(stub_graph_facts):
    stub_graph_facts(
        [
            fact("TREATS", "Type 2 Diabetes Mellitus"),
            fact("CAUSES", "type 2 diabetes mellitus"),  # contradiction, case differs
            fact("CAUSES", "nausea"),
        ]
    )
    out = gen.get_graph_facts_for_drug_curated(None, "Metformin")
    assert out == [fact("TREATS", "Type 2 Diabetes Mellitus"), fact("CAUSES", "nausea")]


def test_causes_are_capped_but_treats_and_contraindications_never_are(stub_graph_facts):
    treats = [fact("TREATS", f"indication {i}") for i in range(10)]
    contra = [fact("CONTRAINDICATED_IN", f"contra {i}") for i in range(10)]
    causes = [fact("CAUSES", f"effect {i}") for i in range(5)]
    stub_graph_facts(causes + contra + treats)  # input order must not matter

    out = gen.get_graph_facts_for_drug_curated(None, "Metformin", max_causes=2)

    assert out == treats + contra + causes[:2]  # grouped order; first N causes kept


def test_default_cap_is_eight_causes(stub_graph_facts):
    stub_graph_facts([fact("CAUSES", f"effect {i}") for i in range(12)])
    out = gen.get_graph_facts_for_drug_curated(None, "Metformin")
    assert [f["disease"] for f in out] == [f"effect {i}" for i in range(8)]


def test_zero_cap_drops_all_causes(stub_graph_facts):
    stub_graph_facts([fact("TREATS", "a"), fact("CAUSES", "b")])
    out = gen.get_graph_facts_for_drug_curated(None, "Metformin", max_causes=0)
    assert out == [fact("TREATS", "a")]


def test_disease_both_treated_and_contraindicated_keeps_both_facts(stub_graph_facts):
    stub_graph_facts([fact("TREATS", "x"), fact("CONTRAINDICATED_IN", "x")])
    out = gen.get_graph_facts_for_drug_curated(None, "Metformin")
    assert [f["relationship"] for f in out] == ["TREATS", "CONTRAINDICATED_IN"]


def test_no_facts_gives_empty_list(stub_graph_facts):
    stub_graph_facts([])
    assert gen.get_graph_facts_for_drug_curated(None, "Metformin") == []


# --------------------------------------------------------------------------
# format_graph_facts
# --------------------------------------------------------------------------
def test_no_facts_formats_to_empty_string():
    assert gen.format_graph_facts([]) == ""


def test_facts_are_listed_with_the_priority_instruction():
    out = gen.format_graph_facts([fact("TREATS", "type 2 diabetes mellitus")])
    assert "Verified structured facts" in out
    assert "- Metformin TREATS type 2 diabetes mellitus" in out
    assert "prioritize these facts" in out


# --------------------------------------------------------------------------
# generate_answer wiring
# --------------------------------------------------------------------------
class FakeOpenAIChat:
    def __init__(self, reply="Answer [1]."):
        self.calls = []
        self._reply = reply
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages):
        self.calls.append({"model": model, "messages": messages})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self._reply))])


@pytest.fixture
def retrieval(monkeypatch):
    """Fake search_with_reranking; records its arguments."""
    state = SimpleNamespace(calls=[], results=[make_result(1), make_result(2, "who")])

    def fake(client, query, candidate_pool_size, top_n):
        state.calls.append((client, query, candidate_pool_size, top_n))
        return state.results

    monkeypatch.setattr(gen, "search_with_reranking", fake)
    return state


def system_prompt(openai_client):
    return openai_client.calls[0]["messages"][0]["content"]


def test_generate_answer_returns_the_model_text_and_forwards_retrieval_defaults(retrieval):
    openai_client = FakeOpenAIChat(reply="Metformin is first-line [1].")
    qdrant = object()

    answer = gen.generate_answer("What is first-line for T2D?", qdrant, openai_client)

    assert answer == "Metformin is first-line [1]."
    assert retrieval.calls == [(qdrant, "What is first-line for T2D?", 20, 5)]


def test_generate_answer_forwards_custom_pool_size_top_n_and_model(retrieval):
    openai_client = FakeOpenAIChat()
    gen.generate_answer(
        "q", object(), openai_client, model="gpt-5.2", candidate_pool_size=7, top_n=3
    )
    assert retrieval.calls[0][2:] == (7, 3)
    assert openai_client.calls[0]["model"] == "gpt-5.2"


def test_default_model_is_gpt_4_1_nano(retrieval):
    openai_client = FakeOpenAIChat()
    gen.generate_answer("q", object(), openai_client)
    assert openai_client.calls[0]["model"] == "gpt-4.1-nano"


def test_prompt_has_system_context_then_the_raw_user_query(retrieval):
    openai_client = FakeOpenAIChat()
    gen.generate_answer("  my exact question? ", object(), openai_client)

    system, user = openai_client.calls[0]["messages"]
    assert (system["role"], user["role"]) == ("system", "user")
    assert user["content"] == "  my exact question? "  # passed through untouched
    assert "[1] (source: pubmed)\nraw text 1" in system["content"]
    assert "[2] (source: who)\nraw text 2" in system["content"]


def test_without_a_neo4j_driver_no_graph_section_is_added(retrieval):
    openai_client = FakeOpenAIChat()
    gen.generate_answer("metformin side effects", object(), openai_client, neo4j_driver=None)
    assert "Verified structured facts" not in system_prompt(openai_client)


def test_graph_facts_are_injected_when_the_query_mentions_a_known_drug(retrieval, monkeypatch):
    monkeypatch.setattr(gen, "get_all_known_drug_names", lambda driver: ["metformin"])
    monkeypatch.setattr(
        gen,
        "get_graph_facts_for_drug_curated",
        lambda driver, drug: [fact("TREATS", "type 2 diabetes mellitus")],
    )
    openai_client = FakeOpenAIChat()

    gen.generate_answer("Is metformin safe?", object(), openai_client, neo4j_driver=object())

    prompt = system_prompt(openai_client)
    assert "Verified structured facts" in prompt
    assert "- Metformin TREATS type 2 diabetes mellitus" in prompt


def test_graph_is_not_queried_when_no_known_drug_is_mentioned(retrieval, monkeypatch):
    monkeypatch.setattr(gen, "get_all_known_drug_names", lambda driver: ["metformin"])

    def must_not_run(driver, drug):
        raise AssertionError("graph facts should not be fetched")

    monkeypatch.setattr(gen, "get_graph_facts_for_drug_curated", must_not_run)
    openai_client = FakeOpenAIChat()

    gen.generate_answer("What is hypertension?", object(), openai_client, neo4j_driver=object())

    assert "Verified structured facts" not in system_prompt(openai_client)


def test_braces_in_retrieved_text_do_not_break_prompt_formatting(retrieval):
    retrieval.results = [make_result(1, raw_text="set {x} and {0} and {context}")]
    openai_client = FakeOpenAIChat()

    gen.generate_answer("q", object(), openai_client)

    assert "set {x} and {0} and {context}" in system_prompt(openai_client)
