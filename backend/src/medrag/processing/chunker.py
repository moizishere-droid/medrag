"""
Source-aware text chunking, built from the techniques tested and validated
in Phase 6 (notebooks/phase06_chunking.ipynb).

Final decisions per source (see docs/phase06_report.md for the full
comparison and reasoning):
  - PubMed abstracts: minimal splitting (already close to one natural chunk)
  - OpenFDA: field-based (each labeled section is already a coherent chunk)
  - WHO clean_text: sentence-based chunking, spaCy sentencizer + a custom
    medical-abbreviation fix (NOT spaCy's statistical parser, which refused
    manual sentence-boundary overrides)
  - WHO tables: each table is kept as one atomic chunk where it fits under
    the embedding model's token limit, or split into row-groups if it
    doesn't (see _split_table_by_rows)
  - WHO images: not chunked at all - handled separately in Phase 8

Section-header-based chunking was tested and rejected: it worked well on
well-structured documents (hypertension, malaria, typhoid) but produced
unreliable results elsewhere (false-positive-inflated counts on breast
cancer/anemia in pregnancy, near-zero detection on mhGAP-based documents,
TB, and COVID-19) - a safe adaptive threshold would have needed non-trivial
extra validation logic not justified by the benefit.

Chunks from a document/drug/article shared across multiple project topics
(WHO shared guidelines, OpenFDA drugs used for multiple conditions, PubMed
papers relevant to multiple topics - all confirmed as real in this
project's data) are built ONCE by the caller (run_chunking.py), which
groups by the underlying content's identity and passes the full list of
topics it belongs to, rather than duplicating the same content once per
topic.
"""

import re
import logging
from typing import List, Optional
from uuid import uuid5, NAMESPACE_URL

import tiktoken
import spacy
from spacy.language import Language

from medrag.ingestion.models import Article, DrugRecord, Guideline
from medrag.processing.models import Chunk

logger = logging.getLogger("medrag.processing")

ENCODING = tiktoken.get_encoding("cl100k_base")  # matches text-embedding-3-small

ABBREVIATIONS = {
    "Fig", "Eq", "Ref", "Vol", "e.g.", "i.e.", "vs.", "Dr", "Mr", "Mrs",
    "et al", "approx", "cf", "mg", "mL", "no", "cm", "kg",
}

_nlp: Optional[Language] = None


def get_spacy_pipeline() -> Language:
    """
    Build (once) and return the spaCy pipeline used for sentence splitting.
    Uses the rule-based sentencizer, not the statistical parser - the parser
    recalculates its own sentence starts and refuses manual overrides
    (raises ValueError: E043 if you try). parser and ner are both excluded
    (neither needed for sentence splitting), which also lets max_length be
    raised safely to handle the largest WHO document (malaria, ~1.18M chars)
    without the components that limit exists to protect against.
    """
    global _nlp
    if _nlp is not None:
        return _nlp

    nlp = spacy.load("en_core_web_sm", exclude=["parser", "ner"])
    nlp.max_length = 2_000_000
    nlp.add_pipe("sentencizer")

    @Language.component("fix_abbreviation_boundaries")
    def fix_abbreviation_boundaries(doc):
        for i, token in enumerate(doc[:-1]):
            text = token.text.rstrip(".")
            is_abbrev = text in ABBREVIATIONS or token.text in ABBREVIATIONS
            if is_abbrev:
                if token.text != "." and i + 1 < len(doc) and doc[i + 1].text == "." and i + 2 < len(doc):
                    doc[i + 2].is_sent_start = False
                elif i + 1 < len(doc):
                    doc[i + 1].is_sent_start = False
        return doc

    nlp.add_pipe("fix_abbreviation_boundaries", after="sentencizer")
    _nlp = nlp
    return _nlp


def spacy_sentence_split(text: str) -> List[str]:
    """Split text into sentences, correctly handling medical abbreviations
    (Fig., e.g., vs., mg., etc.) that a naive regex splitter breaks on."""
    nlp = get_spacy_pipeline()
    doc = nlp(text)
    return [sent.text.strip() for sent in doc.sents if sent.text.strip()]


def sentence_based_chunk(text: str, target_tokens: int = 300) -> List[str]:
    """Group spaCy-detected sentences into target-sized chunks, never
    cutting a sentence mid-way."""
    sentences = spacy_sentence_split(text)

    chunks = []
    current_chunk = []
    current_tokens = 0

    for sentence in sentences:
        sentence_tokens = len(ENCODING.encode(sentence))

        if current_tokens + sentence_tokens > target_tokens and current_chunk:
            chunks.append(" ".join(current_chunk))
            current_chunk = []
            current_tokens = 0

        current_chunk.append(sentence)
        current_tokens += sentence_tokens

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks


def _build_chunk(chunk_id: str, text: str, raw_text: str, source: str, topics: List[str],
                  source_id: str, chunk_index: int, chunk_type: str = "text",
                  metadata: Optional[dict] = None) -> Chunk:
    """Shared helper: builds a Chunk with its deterministic point_id derived from chunk_id."""
    return Chunk(
        chunk_id=chunk_id,
        point_id=Chunk.make_point_id(chunk_id),
        text=text,
        raw_text=raw_text,
        source=source,
        topics=topics,
        source_id=source_id,
        chunk_index=chunk_index,
        chunk_type=chunk_type,
        metadata=metadata,
    )


# --- PubMed ----------------------------------------------------------------

def chunk_pubmed_article(article: Article, topics: List[str], target_tokens: int = 500) -> List[Chunk]:
    """
    Chunk a PubMed article's abstract. Abstracts are typically short enough
    (~1,900 chars average) to stay as one chunk; sentence_based_chunk only
    splits further if a particular abstract genuinely exceeds target_tokens.

    topics is the full list of project topics this article was returned
    under. A single paper genuinely can be relevant to more than one topic
    (confirmed as real overlap in this project's data, ~10% of PubMed
    articles, not a search-matching bug). Callers must group by pmid across
    all topics and call this once per unique article.

    Each chunk's text is prefixed with the article title for context.
    """
    raw_texts = sentence_based_chunk(article.abstract, target_tokens=target_tokens)
    return [
        _build_chunk(
            chunk_id=f"{article.pmid}_pubmed_{i}",
            text=f"{article.title}: {raw_text}",
            raw_text=raw_text,
            source="pubmed",
            topics=topics,
            source_id=article.pmid,
            chunk_index=i,
            chunk_type="text",
            metadata={"title": article.title},
        )
        for i, raw_text in enumerate(raw_texts)
    ]


# --- OpenFDA -----------------------------------------------------------------

def chunk_openfda_drug(drug: DrugRecord, topics: List[str], target_tokens: int = 300) -> List[Chunk]:
    """
    Chunk an OpenFDA drug record field-by-field - each labeled section
    (indications, dosage, contraindications, etc.) is already a coherent
    unit. Fields long enough to exceed target_tokens are sub-split with
    sentence_based_chunk rather than kept as one oversized chunk.

    topics is the full list of project topics this drug legitimately
    appeared under (confirmed as real, e.g. naproxen across osteoarthritis,
    rheumatoid arthritis, etc.). Callers must group by brand_name across
    all topics and call this once per unique drug.

    Each chunk's text is prefixed with "{brand_name} — {readable field
    name}:" for context.
    """
    field_labels = {
        "indications_and_usage": "Indications and Usage",
        "dosage_and_administration": "Dosage and Administration",
        "contraindications": "Contraindications",
        "warnings_and_cautions": "Warnings and Cautions",
        "adverse_reactions": "Adverse Reactions",
        "drug_interactions": "Drug Interactions",
        "mechanism_of_action": "Mechanism of Action",
    }
    fields = {
        "indications_and_usage": drug.indications_and_usage,
        "dosage_and_administration": drug.dosage_and_administration,
        "contraindications": drug.contraindications,
        "warnings_and_cautions": drug.warnings_and_cautions,
        "adverse_reactions": drug.adverse_reactions,
        "drug_interactions": drug.drug_interactions,
        "mechanism_of_action": drug.mechanism_of_action,
    }

    chunks = []
    index = 0
    for field_name, field_text in fields.items():
        if not field_text:
            continue

        field_tokens = len(ENCODING.encode(field_text))
        raw_texts = [field_text] if field_tokens <= target_tokens else sentence_based_chunk(field_text, target_tokens=target_tokens)

        prefix = f"{drug.brand_name} — {field_labels[field_name]}"
        for raw_text in raw_texts:
            chunks.append(_build_chunk(
                chunk_id=f"{drug.brand_name}_openfda_{index}",
                text=f"{prefix}: {raw_text}",
                raw_text=raw_text,
                source="openfda",
                topics=topics,
                source_id=drug.brand_name,
                chunk_index=index,
                chunk_type="text",
                metadata={"field": field_name},
            ))
            index += 1

    return chunks


# --- WHO ---------------------------------------------------------------------

def _token_window_fallback_split(content_text: str, prefix: str, max_tokens: int = 7500) -> List[str]:
    """
    Last-resort fallback: split raw content into token windows sized to
    leave room for the context prefix, then prepend that SAME prefix to
    EVERY resulting piece - not just the first. Only reached when row-group
    splitting still isn't enough (e.g. a single table row containing one
    very large text cell - row-grouping alone can't help when the
    oversized content is inside one row, not spread across many).

    Splitting the already-prefixed text as one blob would only keep the
    prefix on the first piece; every later piece would be bare,
    context-free continuation text with no title/page/part information -
    defeating the purpose of contextual prefixing applied everywhere else
    in this module. Reserving prefix-sized budget and re-prepending it to
    each piece keeps every piece self-contained for embedding.
    """
    prefix_tokens = len(ENCODING.encode(prefix))
    content_budget = max(max_tokens - prefix_tokens, 500)  # keep a sane floor

    content_tokens = ENCODING.encode(content_text)
    if len(content_tokens) + prefix_tokens <= max_tokens:
        return [f"{prefix}{content_text}"]

    pieces = []
    for i in range(0, len(content_tokens), content_budget):
        piece_content = ENCODING.decode(content_tokens[i:i + content_budget])
        pieces.append(f"{prefix}{piece_content}")
    return pieces


def _split_table_by_rows(table_data: list, max_tokens: int = 6000) -> List[list]:
    """
    Split a table's rows into groups that each stay under max_tokens.
    Used only for tables large enough to exceed the embedding model's hard
    8,192-token input limit - most tables stay as a single atomic chunk,
    but a genuinely large table (many rows, e.g. some of the 275 tables in
    the 451-page malaria guideline) needs row-group splitting rather than
    being silently truncated or rejected by the embedding API.

    Note: this alone does not guarantee every group is small enough - a
    single row can itself exceed max_tokens (e.g. one cell with a huge
    block of text). chunk_who_guideline applies _hard_token_split as a
    final safety net to guarantee correctness regardless of this case.
    """
    groups = []
    current_rows = []
    current_tokens = 0

    for row in table_data:
        row_text = " | ".join(str(cell) if cell is not None else "" for cell in row)
        row_tokens = len(ENCODING.encode(row_text))

        if current_rows and current_tokens + row_tokens > max_tokens:
            groups.append(current_rows)
            current_rows = []
            current_tokens = 0

        current_rows.append(row)
        current_tokens += row_tokens

    if current_rows:
        groups.append(current_rows)

    return groups


def chunk_who_guideline(guideline: Guideline, tables: List[dict], topics: List[str], target_tokens: int = 300) -> List[Chunk]:
    """
    Chunk a WHO guideline: clean_text via sentence-based chunking (the
    validated final strategy), plus each extracted table kept as one atomic
    chunk where it fits under the embedding model's token limit, or split
    into row-groups if it doesn't (see _split_table_by_rows). Images are
    not chunked - handled separately in Phase 8.

    topics is the full list of project topics this document (or shared
    document group, e.g. the PEN package covering both asthma and copd)
    belongs to - a canonical id (topics joined with "+") is used for
    chunk_id/source_id so shared documents are chunked once, not once per
    topic.

    Each chunk's text is prefixed with the guideline's title for context.
    """
    canonical_id = "+".join(sorted(topics))
    chunks = []
    index = 0

    text_raws = sentence_based_chunk(guideline.clean_text, target_tokens=target_tokens)
    for raw_text in text_raws:
        chunks.append(_build_chunk(
            chunk_id=f"{canonical_id}_who_text_{index}",
            text=f"{guideline.title}: {raw_text}",
            raw_text=raw_text,
            source="who",
            topics=topics,
            source_id=canonical_id,
            chunk_index=index,
            chunk_type="text",
            metadata={"title": guideline.title},
        ))
        index += 1

    for table in tables:
        table_data = table["table_data"]
        full_table_text = "\n".join(
            " | ".join(str(cell) if cell is not None else "" for cell in row)
            for row in table_data
        )
        full_table_tokens = len(ENCODING.encode(full_table_text))

        if full_table_tokens <= 6000:
            # Fits comfortably under the embedding model's 8,192-token
            # limit as one atomic chunk - the normal case for most tables
            prefixed_text = f"{guideline.title} (table, page {table['page_number']}): {full_table_text}"
            chunks.append(_build_chunk(
                chunk_id=f"{canonical_id}_who_table_{index}",
                text=prefixed_text,
                raw_text=full_table_text,
                source="who",
                topics=topics,
                source_id=canonical_id,
                chunk_index=index,
                chunk_type="table",
                metadata={"title": guideline.title, "page_number": table["page_number"]},
            ))
            index += 1
            continue

        # Table too large for one chunk - split by rows first
        row_groups = _split_table_by_rows(table_data)

        for group_idx, row_group in enumerate(row_groups):
            group_text = "\n".join(
                " | ".join(str(cell) if cell is not None else "" for cell in row)
                for row in row_group
            )
            group_prefix = (
                f"{guideline.title} (table, page {table['page_number']}, "
                f"part {group_idx + 1}/{len(row_groups)}): "
            )

            # Safety net: even a single row-group can still exceed the
            # embedding limit if it contains one very large cell - split
            # further by token windows, with the context prefix re-applied
            # to every resulting piece (not just the first)
            final_pieces = _token_window_fallback_split(group_text, group_prefix)

            for sub_idx, piece_text in enumerate(final_pieces):
                metadata = {
                    "title": guideline.title,
                    "page_number": table["page_number"],
                    "table_part": group_idx + 1,
                    "table_parts_total": len(row_groups),
                }
                if len(final_pieces) > 1:
                    metadata["token_split_part"] = sub_idx + 1
                    metadata["token_split_parts_total"] = len(final_pieces)

                chunks.append(_build_chunk(
                    chunk_id=f"{canonical_id}_who_table_{index}",
                    text=piece_text,
                    raw_text=piece_text,
                    source="who",
                    topics=topics,
                    source_id=canonical_id,
                    chunk_index=index,
                    chunk_type="table",
                    metadata=metadata,
                ))
                index += 1

    return chunks