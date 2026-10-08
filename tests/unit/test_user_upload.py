"""Unit tests for user-uploaded document handling (Phase 19).

PDF extraction runs against real PDFs generated in-test (no fixture files).
Embedding and Qdrant are faked. The last test is a cross-module CONTRACT test:
what the write path stores must be exactly what the read-path filter matches on.
"""

import importlib
from types import SimpleNamespace

import numpy as np
import pytest
from qdrant_client.http import models as qmodels

from medrag.embeddings.qdrant_client import (
    DENSE_VECTOR_NAME,
    SPARSE_VECTOR_NAME,
    TEXT_COLLECTION,
)
from medrag.processing.models import Chunk
from medrag.retrieval.hybrid_search import build_user_filter

uu = importlib.import_module("medrag.ingestion.user_upload")


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def make_pdf(pages):
    """Build a minimal valid PDF with one line of Helvetica text per page.
    An empty string produces a page with no text at all."""
    objects = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(len(pages)))
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode()

    for i, text in enumerate(pages):
        page_no, content_no = 4 + 2 * i, 5 + 2 * i
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode() if text else b""
        objects[page_no] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {content_no} 0 R /Resources << /Font << /F1 3 0 R >> >> >>"
        ).encode()
        objects[content_no] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for num in sorted(objects):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode() + objects[num] + b"\nendobj\n"
    xref_pos = len(out)
    size = max(objects) + 1
    out += f"xref\n0 {size}\n".encode() + b"0000000000 65535 f \n"
    for num in range(1, size):
        out += f"{offsets[num]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF\n".encode()
    return bytes(out)


# --------------------------------------------------------------------------
# validate_upload_size
# --------------------------------------------------------------------------
def test_size_limit_is_20_mb():
    assert uu.MAX_FILE_SIZE_BYTES == 20 * 1024 * 1024


def test_file_exactly_at_the_limit_is_accepted():
    uu.validate_upload_size(bytes(uu.MAX_FILE_SIZE_BYTES))  # must not raise


def test_file_one_byte_over_the_limit_is_rejected():
    with pytest.raises(uu.UploadTooLargeError, match="exceeds the 20 MB limit"):
        uu.validate_upload_size(bytes(uu.MAX_FILE_SIZE_BYTES + 1))


# --------------------------------------------------------------------------
# extract_text_from_pdf
# --------------------------------------------------------------------------
def test_extracts_text_from_a_real_pdf():
    assert uu.extract_text_from_pdf(make_pdf(["Hello medical world"])) == "Hello medical world"


def test_pages_are_joined_with_blank_lines_and_empty_pages_are_skipped():
    pdf = make_pdf(["Alpha page", "", "Beta page"])
    assert uu.extract_text_from_pdf(pdf) == "Alpha page\n\nBeta page"


@pytest.mark.parametrize("garbage", [b"this is not a pdf", b""])
def test_unreadable_bytes_raise_extraction_error(garbage):
    with pytest.raises(uu.UploadExtractionError, match="Could not open or read PDF"):
        uu.extract_text_from_pdf(garbage)


def test_pdf_with_no_text_layer_raises_a_clear_error():
    with pytest.raises(uu.UploadExtractionError, match="No extractable text"):
        uu.extract_text_from_pdf(make_pdf([""]))


# --------------------------------------------------------------------------
# chunk_user_upload (sentence chunking faked: only the tagging is under test)
# --------------------------------------------------------------------------
@pytest.fixture
def fake_chunking(monkeypatch):
    calls = []

    def fake(text, target_tokens):
        calls.append((text, target_tokens))
        return ["First chunk.", "Second chunk."]

    monkeypatch.setattr(uu, "sentence_based_chunk", fake)
    return calls


def test_chunks_carry_all_three_ids_and_the_filename(fake_chunking):
    chunks = uu.chunk_user_upload(
        "body", user_id="u1", session_id="s1", document_id="d1", filename="labs.pdf"
    )

    assert [c.chunk_id for c in chunks] == ["d1_upload_0", "d1_upload_1"]
    assert [c.chunk_index for c in chunks] == [0, 1]
    for c in chunks:
        assert c.metadata == {
            "filename": "labs.pdf",
            "user_id": "u1",
            "session_id": "s1",
            "document_id": "d1",
        }
        assert c.source == "user_upload"
        assert c.source_id == "d1"
        assert c.topics == []
        assert c.chunk_type == "text"
        assert c.point_id == Chunk.make_point_id(c.chunk_id)
    assert chunks[0].text == "labs.pdf: First chunk."  # filename prefix is embedded
    assert chunks[0].raw_text == "First chunk."  # but not stored in raw_text


def test_target_tokens_default_and_override_are_forwarded(fake_chunking):
    uu.chunk_user_upload("body", "u", "s", "d", "f.pdf")
    uu.chunk_user_upload("body", "u", "s", "d", "f.pdf", target_tokens=123)
    assert fake_chunking == [("body", uu.DEFAULT_TARGET_TOKENS), ("body", 123)]


# --------------------------------------------------------------------------
# embed_and_upsert_upload_chunks (OpenAI, fastembed and Qdrant faked)
# --------------------------------------------------------------------------
class FakeOpenAI:
    def __init__(self):
        self.calls = []
        self.embeddings = SimpleNamespace(create=self._create)

    def _create(self, model, input):
        self.calls.append({"model": model, "input": input})
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[float(i), 0.5]) for i in range(len(input))]
        )


class FakeSparseModel:
    def embed(self, texts):
        return (
            SimpleNamespace(indices=np.array([i, i + 10]), values=np.array([0.5, 0.25]))
            for i in range(len(texts))
        )


class FakeQdrantWriter:
    def __init__(self):
        self.upserts = []

    def upsert(self, collection_name, points, wait=True):
        self.upserts.append((collection_name, points))

    def set_payload(self, collection_name, payload, points, wait=True):
        for _, stored in self.upserts:
            for point in stored:
                if passes_filter(points, point.payload):
                    point.payload.update(payload)


@pytest.fixture
def upserted(monkeypatch, fake_chunking):
    """Run the full write path with fakes. Returns (chunks, openai, points)."""
    monkeypatch.setattr(uu, "get_sparse_model", lambda: FakeSparseModel())
    chunks = uu.chunk_user_upload("body", "u1", "s1", "d1", "labs.pdf")
    openai_client, qdrant = FakeOpenAI(), FakeQdrantWriter()

    count = uu.embed_and_upsert_upload_chunks(chunks, qdrant, openai_client)

    assert count == len(chunks)
    assert len(qdrant.upserts) == 1
    collection, points = qdrant.upserts[0]
    assert collection == TEXT_COLLECTION  # same collection as the curated corpus
    return chunks, openai_client, points


def test_embeds_the_prefixed_chunk_text_in_one_batch(upserted):
    chunks, openai_client, _ = upserted
    assert len(openai_client.calls) == 1
    assert openai_client.calls[0]["model"] == "text-embedding-3-small"
    assert openai_client.calls[0]["input"] == [c.text for c in chunks]


def test_points_carry_dense_and_sparse_vectors_and_the_chunk_point_id(upserted):
    chunks, _, points = upserted
    for chunk, point in zip(chunks, points):
        assert point.id == chunk.point_id
        assert set(point.vector) == {DENSE_VECTOR_NAME, SPARSE_VECTOR_NAME}
        assert isinstance(point.vector[SPARSE_VECTOR_NAME], qmodels.SparseVector)
    assert points[0].vector[DENSE_VECTOR_NAME] == [0.0, 0.5]
    assert points[1].vector[DENSE_VECTOR_NAME] == [1.0, 0.5]


def test_payload_has_top_level_isolation_ids_and_citation_fields(upserted):
    _, _, points = upserted
    payload = points[0].payload
    assert payload["user_id"] == "u1"
    assert payload["session_id"] == "s1"
    assert payload["document_id"] == "d1"
    assert payload["source"] == "user_upload"
    assert payload["chunk_id"] == "d1_upload_0"
    assert payload["raw_text"] == "First chunk."
    assert payload["linked_images"] == []
    assert payload["metadata"]["filename"] == "labs.pdf"  # what citations.py reads


def passes_filter(flt, payload):
    """Tiny local evaluator for the two condition types build_user_filter emits
    (OR semantics). Real enforcement by Qdrant is an integration test."""
    if flt is None:
        return True
    def matches(cond):
        if isinstance(cond, qmodels.Filter):
            return passes_filter(cond, payload)
        if isinstance(cond, qmodels.IsEmptyCondition):
            return not payload.get(cond.is_empty.key)
        if isinstance(cond, qmodels.FieldCondition):
            if isinstance(cond.match, qmodels.MatchAny):
                return payload.get(cond.key) in cond.match.any
            return payload.get(cond.key) == cond.match.value
        return False
    return all(matches(c) for c in flt.must or []) and (not flt.should or any(matches(c) for c in flt.should)) and not any(matches(c) for c in flt.must_not or [])


def test_contract_uploaded_chunks_are_visible_to_their_owner_only(upserted):
    """CONTRACT: the key the write path stores (payload['user_id']) must be the
    key the read path filters on. If either side is renamed alone, uploads leak
    to everyone or become invisible to their owner, with no exception raised."""
    _, _, points = upserted
    upload_payload = points[0].payload
    curated_payload = {"chunk_id": "who_1", "source": "who"}  # curated: no user_id field

    assert passes_filter(build_user_filter("u1"), upload_payload)  # owner sees it
    assert not passes_filter(build_user_filter("u2"), upload_payload)  # others do not
    assert passes_filter(build_user_filter("u2"), curated_payload)  # corpus stays visible
    assert passes_filter(build_user_filter("u1"), curated_payload)
    legacy_upload = {"source": "user_upload", "chunk_id": "legacy"}
    assert not passes_filter(build_user_filter(None), legacy_upload)
    assert not passes_filter(build_user_filter("u1"), legacy_upload)


def test_upload_page_and_extracted_text_budgets_are_enforced(monkeypatch):
    monkeypatch.setattr(uu,"MAX_UPLOAD_PAGES",1)
    with pytest.raises(uu.UploadExtractionError,match="page upload limit"):
        uu.extract_text_from_pdf(make_pdf(["One","Two"]))
    monkeypatch.setattr(uu,"MAX_EXTRACTED_CHARACTERS",3)
    with pytest.raises(uu.UploadExtractionError,match="too much extracted text"):
        uu.extract_text_from_pdf(make_pdf(["Long text"]))
