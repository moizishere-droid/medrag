"""Unit tests for the citation system (Phase 15).

Pure logic over plain dicts: no Qdrant, no network. Only
build_who_source_url_lookup touches disk, and it does so through tmp_path.
"""

import json
import logging

import pytest

from medrag.citations import citations as cit
from medrag.citations.citations import (
    build_citations,
    build_who_source_url_lookup,
    extract_used_citation_numbers,
    get_display_info,
    get_who_source_url,
)


@pytest.fixture(autouse=True)
def reset_who_cache(monkeypatch):
    """build_who_source_url_lookup caches at module level. Without this reset,
    a test that fills the cache would leak into every test that runs after it."""
    monkeypatch.setattr(cit, "_who_source_url_cache", None)


def make_payload(source, source_id, chunk_id="c1", **metadata):
    return {
        "chunk_id": chunk_id,
        "source": source,
        "source_id": source_id,
        "metadata": metadata,
    }


def result(chunk_id, source="pubmed", source_id="111", linked_images=None, **metadata):
    payload = make_payload(source, source_id, chunk_id=chunk_id, **metadata)
    if linked_images is not None:
        payload["linked_images"] = linked_images
    return {"payload": payload}


# --------------------------------------------------------------------------
# extract_used_citation_numbers
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text, expected",
    [
        ("", set()),
        ("No markers here.", set()),
        ("Metformin is first-line [1].", {1}),
        ("Two sources [1][3].", {1, 3}),
        ("Repeated [2] and again [2].", {2}),
        ("Multi-digit [10] and [12].", {10, 12}),
        ("Malformed: [a] [1a] [ 1 ] [].", set()),
    ],
)
def test_extract_used_citation_numbers(text, expected):
    assert extract_used_citation_numbers(text) == expected


def test_comma_separated_markers_are_not_parsed():
    """Characterization of a known limitation: only the exact '[n]' format from
    the generation prompt is recognized. If the model ever emits '[1, 3]', those
    citations silently disappear. Revisit if it shows up in practice."""
    assert extract_used_citation_numbers("Both agree [1, 3].") == set()


# --------------------------------------------------------------------------
# get_who_source_url
# --------------------------------------------------------------------------
def test_who_url_direct_topic_match():
    urls = {"diabetes": "https://who.int/diabetes"}
    assert get_who_source_url("diabetes", urls) == "https://who.int/diabetes"


def test_who_url_resolves_combined_multi_topic_source_id():
    """Regression (Phase 15): chunks shared by several topics carry 'a+b+c' as
    source_id; a naive direct-key lookup returned None for every one of them."""
    urls = {"hypertension": "https://who.int/htn"}
    assert (
        get_who_source_url("diabetes+hypertension+asthma", urls) == "https://who.int/htn"
    )


def test_who_url_unknown_source_returns_none():
    assert get_who_source_url("nothing+here", {"diabetes": "https://who.int/d"}) is None


def test_who_url_first_matching_topic_wins():
    urls = {"a": "https://who.int/a", "b": "https://who.int/b"}
    assert get_who_source_url("a+b", urls) == "https://who.int/a"


def test_who_url_skips_topics_whose_raw_json_had_no_source_url():
    urls = {"a": None, "b": "https://who.int/b"}
    assert get_who_source_url("a+b", urls) == "https://who.int/b"


# --------------------------------------------------------------------------
# get_display_info, one block per source
# --------------------------------------------------------------------------
def test_display_who_uses_metadata_title_and_resolved_url():
    payload = make_payload("who", "diabetes+obesity", title="WHO Diabetes Guideline")
    info = get_display_info(payload, {"obesity": "https://who.int/obesity"})
    assert info == {"title": "WHO Diabetes Guideline", "url": "https://who.int/obesity"}


def test_display_who_title_falls_back_to_source_id():
    info = get_display_info(make_payload("who", "diabetes"), {})
    assert info == {"title": "diabetes", "url": None}


@pytest.mark.parametrize(
    "field, expected_title",
    [
        ("adverse_reactions", "metformin — FDA Label (Adverse Reactions)"),
        ("indications_and_usage", "metformin — FDA Label (Indications And Usage)"),
        ("contraindications", "metformin — FDA Label (Contraindications)"),
        ("", "metformin — FDA Label"),
    ],
)
def test_display_openfda_constructs_title_and_has_no_url(field, expected_title):
    payload = make_payload("openfda", "metformin", field=field)
    assert get_display_info(payload, {}) == {"title": expected_title, "url": None}


def test_display_openfda_without_field_key():
    info = get_display_info(make_payload("openfda", "metformin"), {})
    assert info == {"title": "metformin — FDA Label", "url": None}


def test_display_pubmed_builds_url_from_pmid():
    payload = make_payload("pubmed", "12345", title="Metformin in T2D")
    assert get_display_info(payload, {}) == {
        "title": "Metformin in T2D",
        "url": "https://pubmed.ncbi.nlm.nih.gov/12345/",
    }


def test_display_pubmed_title_falls_back_to_pmid():
    info = get_display_info(make_payload("pubmed", "12345"), {})
    assert info["title"] == "PubMed article 12345"


def test_display_user_upload_uses_filename_and_has_no_url():
    payload = make_payload("user_upload", "sess-1", filename="my_labs.pdf")
    assert get_display_info(payload, {}) == {"title": "my_labs.pdf", "url": None}


def test_display_user_upload_default_title():
    info = get_display_info(make_payload("user_upload", "sess-1"), {})
    assert info == {"title": "Uploaded document", "url": None}


def test_display_unknown_source_degrades_gracefully_and_warns(caplog):
    with caplog.at_level(logging.WARNING, logger="medrag.citations"):
        info = get_display_info(make_payload("mystery", "x", chunk_id="c42"), {})
    assert info == {"title": "Unknown source", "url": None}
    assert "mystery" in caplog.text


# --------------------------------------------------------------------------
# build_citations
# --------------------------------------------------------------------------
def test_marker_n_maps_to_results_index_n_minus_1():
    results = [
        result("c1", source_id="111"),
        result("c2", source_id="222"),
        result("c3", source_id="333"),
    ]
    cites = build_citations("Supported by [2].", results, {})
    assert len(cites) == 1
    assert cites[0]["marker"] == 2
    assert cites[0]["chunk_id"] == "c2"
    assert cites[0]["url"] == "https://pubmed.ncbi.nlm.nih.gov/222/"


def test_only_markers_used_in_the_answer_are_resolved():
    results = [result("c1"), result("c2"), result("c3")]
    cites = build_citations("Only [1] and [3] were used.", results, {})
    assert [c["chunk_id"] for c in cites] == ["c1", "c3"]


def test_citations_are_ordered_by_marker_not_by_appearance():
    results = [result("c1"), result("c2"), result("c3")]
    cites = build_citations("First [3], then [1].", results, {})
    assert [c["marker"] for c in cites] == [1, 3]


def test_no_markers_returns_empty_list():
    assert build_citations("An answer with no citations.", [result("c1")], {}) == []


def test_out_of_range_markers_are_skipped_not_raised(caplog):
    results = [result("c1"), result("c2")]
    with caplog.at_level(logging.WARNING, logger="medrag.citations"):
        cites = build_citations("Valid [1], hallucinated [0] and [99].", results, {})
    assert [c["marker"] for c in cites] == [1]
    assert "out of range" in caplog.text


def test_marker_with_empty_results_returns_empty_list():
    assert build_citations("Claim [1].", [], {}) == []


def test_citation_object_shape_and_linked_images_passthrough():
    results = [
        result(
            "c1",
            source="who",
            source_id="diabetes",
            linked_images=["img_7"],
            title="WHO Diabetes",
        )
    ]
    (citation,) = build_citations("See [1].", results, {"diabetes": "https://who.int/d"})
    assert citation == {
        "marker": 1,
        "chunk_id": "c1",
        "source": "who",
        "source_id": "diabetes",
        "title": "WHO Diabetes",
        "url": "https://who.int/d",
        "linked_images": ["img_7"],
    }


def test_linked_images_defaults_to_empty_list():
    (citation,) = build_citations("See [1].", [result("c1")], {})
    assert citation["linked_images"] == []


def test_mixed_sources_in_one_answer():
    results = [
        result("c1", source="who", source_id="diabetes", title="WHO Diabetes"),
        result("c2", source="openfda", source_id="metformin", field="warnings"),
        result("c3", source="pubmed", source_id="999", title="A trial"),
        result("c4", source="user_upload", source_id="sess-1", filename="notes.pdf"),
    ]
    cites = build_citations("[1][2][3][4]", results, {"diabetes": "https://who.int/d"})
    assert [(c["source"], c["url"] is None) for c in cites] == [
        ("who", False),
        ("openfda", True),
        ("pubmed", False),
        ("user_upload", True),
    ]


# --------------------------------------------------------------------------
# build_who_source_url_lookup
# --------------------------------------------------------------------------
def test_group_sources_keeps_chunk_markers_and_distinct_documents():
    from medrag.citations.citations import group_citations_by_source
    citations = [dict(marker=n, source="user_upload", source_id=doc, title="same.pdf", url=None)
                 for n, doc in [(1, "a"), (2, "a"), (3, "b")]]
    groups = group_citations_by_source(citations)
    assert [g["markers"] for g in groups] == [[1, 2], [3]]
    assert all("markers" not in c for c in citations)


def test_who_lookup_maps_filename_stem_to_source_url(tmp_path):
    (tmp_path / "diabetes.json").write_text(
        json.dumps({"source_url": "https://who.int/d"}), encoding="utf-8"
    )
    (tmp_path / "asthma.json").write_text(json.dumps({"title": "no url"}), encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignored", encoding="utf-8")

    assert build_who_source_url_lookup(str(tmp_path)) == {
        "diabetes": "https://who.int/d",
        "asthma": None,
    }


def test_who_lookup_is_cached_at_module_level(tmp_path):
    (tmp_path / "t1.json").write_text(
        json.dumps({"source_url": "https://who.int/a"}), encoding="utf-8"
    )
    first = build_who_source_url_lookup(str(tmp_path))

    (tmp_path / "t2.json").write_text(
        json.dumps({"source_url": "https://who.int/b"}), encoding="utf-8"
    )
    assert build_who_source_url_lookup(str(tmp_path)) == first  # served from cache
    assert set(build_who_source_url_lookup(str(tmp_path), use_cache=False)) == {"t1", "t2"}
