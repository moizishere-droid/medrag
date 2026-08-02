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
  - WHO tables: each table is kept as one atomic chunk, never split
  - WHO images: not chunked at all - handled separately in Phase 8

Section-header-based chunking was tested and rejected: it worked well on
well-structured documents (hypertension, malaria, typhoid) but produced
unreliable results elsewhere (false-positive-inflated counts on breast
cancer/anemia in pregnancy, near-zero detection on mhGAP-based documents,
TB, and COVID-19) - a safe adaptive threshold would have needed non-trivial
extra validation logic not justified by the benefit.
"""

import logging
from typing import List, Optional

import tiktoken
import spacy
from spacy.language import Language

from medrag.ingestion.models import Article, DrugRecord, Guideline
from medrag.processing.models import Chunk

logger = logging.getLogger("medrag.processing")

ENCODING = tiktoken.get_encoding("cl100k_base")  # matches text-embedding-3-small

# Abbreviations spaCy's small model does not reliably treat as non-sentence-
# ending on its own (matched with trailing periods stripped, since spaCy
# sometimes tokenizes the period separately, e.g. "Fig" + "." rather than
# keeping "Fig." as one token).
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
    (raises ValueError: E043 if you try), so it can't be used with a custom
    abbreviation-boundary fix.
    """
    global _nlp
    if _nlp is not None:
        return _nlp

    nlp = spacy.load("en_core_web_sm", exclude=["parser", "ner"])
    nlp.max_length = 2_000_000  # malaria's clean_text alone is ~1.18M chars;
                                  # safe to raise since parser/ner (the memory-
                                  # heavy components this limit protects
                                  # against) are excluded - we only use the
                                  # lightweight rule-based sentencizer
    nlp.add_pipe("sentencizer")

    @Language.component("fix_abbreviation_boundaries")
    def fix_abbreviation_boundaries(doc):
        for i, token in enumerate(doc[:-1]):
            text = token.text.rstrip(".")
            is_abbrev = text in ABBREVIATIONS or token.text in ABBREVIATIONS
            if is_abbrev:
                # If the abbreviation's period is its own separate token
                # (e.g. "Fig" + "."), the sentence boundary lands on the
                # token AFTER that period - unset it two tokens ahead.
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


# --- Per-source chunking functions ---------------------------------------

def chunk_pubmed_article(article: Article, target_tokens: int = 500) -> List[Chunk]:
    """
    Chunk a PubMed article's abstract. Abstracts are typically short enough
    (~1,900 chars average) to stay as one chunk; sentence_based_chunk only
    splits further if a particular abstract genuinely exceeds target_tokens.

    Each chunk's text is prefixed with the article title for context, since
    an isolated sentence from a split abstract otherwise loses its anchor
    to which paper it came from (this matters more for OpenFDA/WHO, whose
    fields/sections split far more often, but is applied consistently here
    too for the same reason).
    """
    raw_texts = sentence_based_chunk(article.abstract, target_tokens=target_tokens)
    return [
        Chunk(
            chunk_id=f"{article.topic}_pubmed_{article.pmid}_{i}",
            text=f"{article.title}: {raw_text}",
            raw_text=raw_text,
            source="pubmed",
            topic=article.topic,
            source_id=article.pmid,
            chunk_index=i,
            chunk_type="text",
            metadata={"title": article.title},
        )
        for i, raw_text in enumerate(raw_texts)
    ]


def chunk_openfda_drug(drug: DrugRecord, target_tokens: int = 300) -> List[Chunk]:
    """
    Chunk an OpenFDA drug record field-by-field - each labeled section
    (indications, dosage, contraindications, etc.) is already a coherent
    unit. Fields long enough to exceed target_tokens are sub-split with
    sentence_based_chunk rather than kept as one oversized chunk.

    Each chunk's text is prefixed with "{brand_name} — {readable field
    name}:" for context. Without this, a sub-chunk from the middle of a
    long field like adverse_reactions can read as a generic sentence with
    no indication of which drug or which field it belongs to - weakening
    its embedding similarity to queries like "what are Glimepiride's
    warnings" that name the drug explicitly.
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
            chunks.append(Chunk(
                chunk_id=f"{drug.topic}_openfda_{drug.brand_name}_{index}",
                text=f"{prefix}: {raw_text}",
                raw_text=raw_text,
                source="openfda",
                topic=drug.topic,
                source_id=drug.brand_name,
                chunk_index=index,
                chunk_type="text",
                metadata={"field": field_name},
            ))
            index += 1

    return chunks


def chunk_who_guideline(guideline: Guideline, tables: List[dict], target_tokens: int = 300) -> List[Chunk]:
    """
    Chunk a WHO guideline: clean_text via sentence-based chunking (the
    validated final strategy - see module docstring), plus each extracted
    table kept as one atomic chunk (never split, to preserve row/column
    meaning). Images are not chunked - handled separately in Phase 8.

    Each chunk's text is prefixed with the guideline's title for context,
    same reasoning as PubMed/OpenFDA - an isolated sentence or table from a
    long document otherwise loses its anchor to which guideline it's from.
    """
    chunks = []
    index = 0

    text_raws = sentence_based_chunk(guideline.clean_text, target_tokens=target_tokens)
    for raw_text in text_raws:
        chunks.append(Chunk(
            chunk_id=f"{guideline.topic}_who_text_{index}",
            text=f"{guideline.title}: {raw_text}",
            raw_text=raw_text,
            source="who",
            topic=guideline.topic,
            source_id=guideline.topic,
            chunk_index=index,
            chunk_type="text",
            metadata={"title": guideline.title},
        ))
        index += 1

    for table in tables:
        table_text = "\n".join(
            " | ".join(str(cell) if cell is not None else "" for cell in row)
            for row in table["table_data"]
        )
        chunks.append(Chunk(
            chunk_id=f"{guideline.topic}_who_table_{index}",
            text=f"{guideline.title} (table, page {table['page_number']}): {table_text}",
            raw_text=table_text,
            source="who",
            topic=guideline.topic,
            source_id=guideline.topic,
            chunk_index=index,
            chunk_type="table",
            metadata={"title": guideline.title, "page_number": table["page_number"]},
        ))
        index += 1

    return chunks