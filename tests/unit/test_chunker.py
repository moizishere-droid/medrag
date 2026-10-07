"""Unit tests for text chunking (Phase 5).

Sentence splitting runs on the REAL spaCy pipeline (en_core_web_sm plus the
custom abbreviation fix), because that logic is exactly what is under test.
Token budgets are always measured with chunker.ENCODING itself, so every
assertion holds for whichever tokenizer is installed.

Inputs to the chunk_* builders are SimpleNamespace objects: the builders only
read attributes, so there is no need to construct the real Article / DrugRecord /
Guideline models.
"""

import importlib
from types import SimpleNamespace

import pytest

from medrag.processing.models import Chunk

chunker = importlib.import_module("medrag.processing.chunker")
sentence_based_chunk = chunker.sentence_based_chunk
spacy_sentence_split = chunker.spacy_sentence_split


def ntok(text: str) -> int:
    return len(chunker.ENCODING.encode(text))


SENTENCES = [f"Sentence number {i} talks about topic {i}." for i in range(30)]
TEXT = " ".join(SENTENCES)


# --------------------------------------------------------------------------
# spacy_sentence_split + the abbreviation fix
# --------------------------------------------------------------------------
def test_splitter_recovers_plain_sentences():
    assert spacy_sentence_split(TEXT) == SENTENCES


@pytest.mark.parametrize("text", ["", "   ", "\n\n"])
def test_blank_input_yields_no_sentences(text):
    assert spacy_sentence_split(text) == []


@pytest.mark.parametrize(
    "text, expected",
    [
        (
            "See Fig. 3 for details. Next sentence here.",
            ["See Fig. 3 for details.", "Next sentence here."],
        ),
        (
            "Dr. Smith prescribed 5 mg daily. Follow up in 2 weeks.",
            ["Dr. Smith prescribed 5 mg daily.", "Follow up in 2 weeks."],
        ),
        (
            "Use drugs, e.g. aspirin, for pain. Then rest.",
            ["Use drugs, e.g. aspirin, for pain.", "Then rest."],
        ),
        (
            "Drug A vs. drug B was compared. Results followed.",
            ["Drug A vs. drug B was compared.", "Results followed."],
        ),
        (
            "Refer to Ref. 12 and Vol. 3 for more. Done.",
            ["Refer to Ref. 12 and Vol. 3 for more.", "Done."],
        ),
    ],
    ids=["Fig.", "Dr.", "e.g.", "vs.", "Ref./Vol."],
)
def test_listed_abbreviations_do_not_end_a_sentence(text, expected):
    assert spacy_sentence_split(text) == expected


def test_sentence_ending_in_a_listed_abbreviation_is_not_split_known_tradeoff():
    """Characterization of a deliberate trade-off: because 'mg' is in
    ABBREVIATIONS, a sentence that genuinely ENDS in 'mg.' is merged with the
    next one. Accepted: it only makes a 'sentence' longer, it never loses text."""
    assert spacy_sentence_split("Give 5 mg. Repeat after 4 hours.") == [
        "Give 5 mg. Repeat after 4 hours."
    ]


def test_et_al_does_not_end_a_sentence():
    text = "Smith et al. reported better outcomes. The trial was large."
    assert spacy_sentence_split(text) == [
        "Smith et al. reported better outcomes.",
        "The trial was large.",
    ]


def test_capitalised_approx_does_not_end_a_sentence():
    text = "Approx. 40 patients responded. The rest did not."
    assert spacy_sentence_split(text) == ["Approx. 40 patients responded.", "The rest did not."]


# --------------------------------------------------------------------------
# sentence_based_chunk
# --------------------------------------------------------------------------
def test_empty_text_gives_no_chunks():
    assert sentence_based_chunk("") == []


def test_short_text_is_a_single_chunk():
    assert sentence_based_chunk(TEXT, target_tokens=10**9) == [TEXT]


def test_chunks_keep_every_sentence_whole_and_in_order():
    target = 3 * max(ntok(s) for s in SENTENCES)
    chunks = sentence_based_chunk(TEXT, target_tokens=target)

    assert len(chunks) > 1
    rebuilt = [s for chunk in chunks for s in spacy_sentence_split(chunk)]
    assert rebuilt == SENTENCES  # nothing lost, nothing cut, nothing reordered


def test_chunk_token_sum_never_exceeds_target_unless_a_single_sentence_does():
    target = 3 * max(ntok(s) for s in SENTENCES)
    for chunk in sentence_based_chunk(TEXT, target_tokens=target):
        sentences = spacy_sentence_split(chunk)
        assert len(sentences) == 1 or sum(ntok(s) for s in sentences) <= target


def test_budget_boundary_is_inclusive():
    a, b = "Alpha beta gamma delta.", "Epsilon zeta eta theta."
    both = f"{a} {b}"
    assert sentence_based_chunk(both, target_tokens=ntok(a) + ntok(b)) == [both]
    assert sentence_based_chunk(both, target_tokens=ntok(a) + ntok(b) - 1) == [a, b]


def test_oversized_sentence_is_kept_whole_and_never_yields_an_empty_chunk():
    long_sentence = ("word " * 200 + "end.").strip()
    short = "Short one."
    assert sentence_based_chunk(long_sentence, target_tokens=10) == [long_sentence]
    assert sentence_based_chunk(f"{long_sentence} {short}", target_tokens=10) == [
        long_sentence,
        short,
    ]


# --------------------------------------------------------------------------
# _split_table_by_rows
# --------------------------------------------------------------------------
def row_tokens(row):
    return ntok(" | ".join(str(cell) if cell is not None else "" for cell in row))


def test_empty_table_gives_no_groups():
    assert chunker._split_table_by_rows([]) == []


def test_row_groups_preserve_every_row_in_order_and_respect_the_budget():
    rows = [[f"drug{i}", f"dose {i} " * 5] for i in range(40)]
    budget = 6 * max(row_tokens(r) for r in rows)

    groups = chunker._split_table_by_rows(rows, max_tokens=budget)

    assert len(groups) > 1
    assert [r for g in groups for r in g] == rows
    for g in groups:
        assert len(g) == 1 or sum(row_tokens(r) for r in g) <= budget


def test_single_oversized_row_gets_its_own_group_and_is_not_dropped():
    small = ["a", "b"]
    huge = ["x " * 500, "y"]
    groups = chunker._split_table_by_rows([small, huge, small], max_tokens=row_tokens(small) * 2)
    assert groups == [[small], [huge], [small]]


def test_none_cells_do_not_crash_row_splitting():
    assert chunker._split_table_by_rows([[None, "x"]]) == [[[None, "x"]]]


# --------------------------------------------------------------------------
# _token_window_fallback_split
# --------------------------------------------------------------------------
PREFIX = "Title (table, page 3, part 1/2): "


def test_small_content_is_returned_as_one_prefixed_piece():
    assert chunker._token_window_fallback_split("tiny content", PREFIX) == [PREFIX + "tiny content"]


def test_large_content_is_split_and_the_prefix_is_repeated_on_every_piece():
    content = "word " * 3000
    pieces = chunker._token_window_fallback_split(content, PREFIX, max_tokens=1000)

    assert len(pieces) > 1
    assert all(p.startswith(PREFIX) for p in pieces)  # not only the first piece
    assert "".join(p[len(PREFIX):] for p in pieces) == content  # lossless


# --------------------------------------------------------------------------
# chunk_pubmed_article
# --------------------------------------------------------------------------
def test_pubmed_chunks_are_tagged_and_prefixed_with_the_title():
    abstract = " ".join(SENTENCES[:12])
    article = SimpleNamespace(pmid="123", title="Metformin trial", abstract=abstract)
    topics = ["diabetes", "obesity"]

    chunks = chunker.chunk_pubmed_article(
        article, topics, target_tokens=3 * max(ntok(s) for s in SENTENCES[:12])
    )

    assert len(chunks) > 1
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    for i, c in enumerate(chunks):
        assert c.chunk_id == f"123_pubmed_{i}"
        assert c.point_id == Chunk.make_point_id(c.chunk_id)
        assert c.text == f"Metformin trial: {c.raw_text}"
        assert c.source == "pubmed"
        assert c.source_id == "123"
        assert c.topics == topics
        assert c.chunk_type == "text"
        assert c.metadata == {"title": "Metformin trial"}


# --------------------------------------------------------------------------
# chunk_openfda_drug
# --------------------------------------------------------------------------
FDA_FIELDS = [
    "indications_and_usage",
    "dosage_and_administration",
    "contraindications",
    "warnings_and_cautions",
    "adverse_reactions",
    "drug_interactions",
    "mechanism_of_action",
]


def make_drug(brand_name="Glucophage", **fields):
    values = {name: None for name in FDA_FIELDS}
    values.update(fields)
    return SimpleNamespace(brand_name=brand_name, **values)


def test_openfda_skips_empty_fields_and_indexes_chunks_continuously():
    drug = make_drug(
        indications_and_usage="Treats type 2 diabetes.",
        contraindications="Severe renal impairment.",
        adverse_reactions="Nausea and diarrhea.",
        warnings_and_cautions="",  # empty string is skipped like None
    )

    chunks = chunker.chunk_openfda_drug(drug, topics=["diabetes"])

    assert [c.metadata["field"] for c in chunks] == [
        "indications_and_usage",
        "contraindications",
        "adverse_reactions",
    ]
    assert [c.chunk_id for c in chunks] == [
        "Glucophage_openfda_0",
        "Glucophage_openfda_1",
        "Glucophage_openfda_2",
    ]
    assert [c.chunk_index for c in chunks] == [0, 1, 2]


def test_openfda_chunk_text_uses_brand_and_readable_field_label():
    drug = make_drug(adverse_reactions="Nausea and diarrhea.")
    (chunk,) = chunker.chunk_openfda_drug(drug, topics=["diabetes"])

    assert chunk.text == "Glucophage — Adverse Reactions: Nausea and diarrhea."
    assert chunk.raw_text == "Nausea and diarrhea."
    assert chunk.source == "openfda"
    assert chunk.source_id == "Glucophage"
    assert chunk.topics == ["diabetes"]


def test_openfda_drug_with_no_fields_yields_no_chunks():
    assert chunker.chunk_openfda_drug(make_drug(), topics=["x"]) == []


def test_openfda_short_field_is_never_split_even_with_many_sentences():
    text = " ".join(SENTENCES[:5])
    drug = make_drug(indications_and_usage=text)
    chunks = chunker.chunk_openfda_drug(drug, topics=["x"], target_tokens=ntok(text))
    assert [c.raw_text for c in chunks] == [text]  # <= target stays whole


def test_openfda_oversized_field_is_sub_split_and_index_keeps_counting():
    long_field = " ".join(SENTENCES[:20])
    drug = make_drug(indications_and_usage=long_field, contraindications="Short field.")

    chunks = chunker.chunk_openfda_drug(
        drug, topics=["x"], target_tokens=3 * max(ntok(s) for s in SENTENCES[:20])
    )

    indications = [c for c in chunks if c.metadata["field"] == "indications_and_usage"]
    assert len(indications) > 1
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert chunks[-1].metadata["field"] == "contraindications"
    assert chunks[-1].chunk_index == len(chunks) - 1


# --------------------------------------------------------------------------
# chunk_who_guideline
# --------------------------------------------------------------------------
def make_guideline(clean_text="", title="HTN Guideline"):
    return SimpleNamespace(title=title, clean_text=clean_text)


def make_table(rows, page=1):
    return {"table_data": rows, "page_number": page}


def test_who_with_no_text_and_no_tables_yields_nothing():
    assert chunker.chunk_who_guideline(make_guideline(""), tables=[], topics=["x"]) == []


def test_who_shared_document_uses_sorted_canonical_id_but_keeps_topic_order():
    topics = ["copd", "asthma"]
    chunks = chunker.chunk_who_guideline(
        make_guideline("One sentence only."), tables=[], topics=topics
    )
    (chunk,) = chunks
    assert chunk.chunk_id == "asthma+copd_who_text_0"
    assert chunk.source_id == "asthma+copd"
    assert chunk.topics == topics  # passed through unsorted
    assert chunk.text == "HTN Guideline: One sentence only."
    assert chunk.metadata == {"title": "HTN Guideline"}


def test_who_small_table_is_one_atomic_chunk_and_index_continues_after_text():
    rows = [["Drug", "Dose"], ["lisinopril", None]]
    chunks = chunker.chunk_who_guideline(
        make_guideline("First sentence. Second sentence."),
        tables=[make_table(rows, page=12)],
        topics=["htn"],
    )

    text_chunks = [c for c in chunks if c.chunk_type == "text"]
    (table_chunk,) = [c for c in chunks if c.chunk_type == "table"]

    assert table_chunk.chunk_index == len(text_chunks)
    assert table_chunk.chunk_id == f"htn_who_table_{len(text_chunks)}"
    assert table_chunk.raw_text == "Drug | Dose\nlisinopril | "  # None becomes empty
    assert table_chunk.text == f"HTN Guideline (table, page 12): {table_chunk.raw_text}"
    assert table_chunk.metadata == {"title": "HTN Guideline", "page_number": 12, "table_data": rows}


def test_who_oversized_table_is_split_into_numbered_parts_without_losing_rows():
    rows = [[f"row{i}", "word " * 300] for i in range(30)]
    chunks = chunker.chunk_who_guideline(
        make_guideline(""), tables=[make_table(rows, page=5)], topics=["htn"]
    )

    total = chunks[0].metadata["table_parts_total"]
    assert total > 1
    assert sorted({c.metadata["table_part"] for c in chunks}) == list(range(1, total + 1))
    for c in chunks:
        k = c.metadata["table_part"]
        assert c.text.startswith(f"HTN Guideline (table, page 5, part {k}/{total}): ")
        assert c.metadata["page_number"] == 5
    for i in range(30):  # every row survives exactly once
        assert sum(c.text.count(f"row{i} | ") for c in chunks) == 1


def test_who_single_giant_cell_is_token_split_with_prefix_on_every_piece():
    rows = [["x " * 9000]]
    chunks = chunker.chunk_who_guideline(
        make_guideline(""), tables=[make_table(rows, page=7)], topics=["htn"]
    )

    n = len(chunks)
    prefix = "HTN Guideline (table, page 7, part 1/1): "
    assert n > 1
    assert all(c.text.startswith(prefix) for c in chunks)
    assert [c.metadata["token_split_part"] for c in chunks] == list(range(1, n + 1))
    assert all(c.metadata["token_split_parts_total"] == n for c in chunks)
    assert all(c.metadata["table_parts_total"] == 1 for c in chunks)


def test_who_chunk_ids_and_indexes_are_unique_and_sequential_across_text_and_tables():
    rows = [[f"row{i}", "word " * 300] for i in range(30)]
    chunks = chunker.chunk_who_guideline(
        make_guideline(" ".join(SENTENCES[:10])),
        tables=[make_table(rows, 1), make_table([["a", "b"]], 2)],
        topics=["htn"],
        target_tokens=3 * max(ntok(s) for s in SENTENCES[:10]),
    )

    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
    assert len({c.chunk_id for c in chunks}) == len(chunks)
    assert len({c.point_id for c in chunks}) == len(chunks)
