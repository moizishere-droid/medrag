"""
General-purpose PDF extraction, chunking, and embedding for
user-uploaded documents (Phase 19).

Extraction is deliberately simpler than who_client.py: WHO's extraction
has header/footer stripping and table-region detection tuned
specifically to WHO's document layout - an arbitrary user-uploaded PDF
has no such known structure, so this module does plain page-by-page
text extraction with no structural assumptions. A real, stated scope
tradeoff: user-uploaded documents get less sophisticated extraction
than the curated corpus.

Chunking reuses Phase 5's sentence_based_chunk() directly - it is
already source-agnostic (text in, sentence-grouped chunks out); only
the tagging/metadata wrapping here is new.

Isolation model (the core design of this phase, validated directly
before being adopted): every uploaded chunk is tagged with THREE ids,
not one:
  - user_id: the actual retrieval-isolation boundary. Any chat/session
    belonging to this user can see this upload; a different user's
    queries never can. This is what makes "I have multiple open chats
    like ChatGPT/Claude, and they can all see my own uploads, but a
    different person can't see mine" work.
  - session_id: which specific chat the upload happened in - kept for
    citation display only, not used as a retrieval filter.
  - document_id: distinguishes multiple uploads from each other within
    the same user.
An earlier version of this design used session_id as the isolation
boundary; this was found to be too narrow once multi-chat behavior was
clarified (a user's second open chat couldn't see an upload made in
their first chat) and was replaced with user_id before being used in
production.
"""

import io
import logging
from typing import List

import pdfplumber

from medrag.processing.chunker import sentence_based_chunk
from medrag.processing.models import Chunk
from medrag.embeddings.qdrant_client import DENSE_VECTOR_NAME, SPARSE_VECTOR_NAME, TEXT_COLLECTION

logger = logging.getLogger("medrag.ingestion.user_upload")

MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB
DEFAULT_TARGET_TOKENS = 300
DENSE_EMBEDDING_MODEL = "text-embedding-3-small"
SPARSE_MODEL_NAME = "Qdrant/bm25"

_sparse_model_cache = None


class UploadTooLargeError(Exception):
    pass


class UploadExtractionError(Exception):
    pass


def get_sparse_model():
    """Cached fastembed BM25 encoder - same model used to build every
    other sparse vector in medrag_text (Phase 9), so uploaded chunks'
    sparse vectors live in the same term-hash space as everything else."""
    global _sparse_model_cache
    if _sparse_model_cache is None:
        from fastembed import SparseTextEmbedding
        logger.info(f"Loading sparse model '{SPARSE_MODEL_NAME}'...")
        _sparse_model_cache = SparseTextEmbedding(model_name=SPARSE_MODEL_NAME)
    return _sparse_model_cache


def validate_upload_size(file_bytes: bytes) -> None:
    if len(file_bytes) > MAX_FILE_SIZE_BYTES:
        raise UploadTooLargeError(
            f"File is {len(file_bytes) / (1024*1024):.1f} MB, "
            f"exceeds the {MAX_FILE_SIZE_BYTES / (1024*1024):.0f} MB limit"
        )


def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract plain text from a PDF's bytes, page by page, joined with
    double newlines. No header/footer stripping, no table detection -
    see module docstring for why. Raises UploadExtractionError if the
    PDF can't be opened or yields no extractable text (e.g. a
    scanned/image-only PDF with no OCR layer - a real, expected
    limitation, not a bug)."""
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            pages_text = [page.extract_text() or "" for page in pdf.pages]
    except Exception as e:
        raise UploadExtractionError(f"Could not open or read PDF: {e}") from e

    full_text = "\n\n".join(t for t in pages_text if t.strip())

    if not full_text.strip():
        raise UploadExtractionError(
            "No extractable text found - this may be a scanned/image-only "
            "PDF with no text layer, which this feature does not OCR."
        )

    return full_text


def chunk_user_upload(
    text: str,
    user_id: str,
    session_id: str,
    document_id: str,
    filename: str,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
) -> List[Chunk]:
    """Chunk a user-uploaded document's extracted text. See module
    docstring for the user_id / session_id / document_id tagging
    scheme - user_id is the real isolation boundary, the other two are
    for display/distinction only."""
    raw_texts = sentence_based_chunk(text, target_tokens=target_tokens)
    chunks = []
    for i, raw_text in enumerate(raw_texts):
        chunk_id = f"{document_id}_upload_{i}"
        chunks.append(Chunk(
            chunk_id=chunk_id,
            point_id=Chunk.make_point_id(chunk_id),
            text=f"{filename}: {raw_text}",
            raw_text=raw_text,
            source="user_upload",
            topics=[],
            source_id=document_id,
            chunk_index=i,
            chunk_type="text",
            metadata={
                "filename": filename,
                "user_id": user_id,
                "session_id": session_id,
                "document_id": document_id,
            },
        ))
    return chunks


def embed_and_upsert_upload_chunks(chunks: List[Chunk], qdrant_client, openai_client) -> int:
    """Embed (dense + sparse, matching Phase 9's hybrid schema) and
    upsert uploaded chunks into the SAME medrag_text collection used by
    the curated corpus - a purely additive write. Every existing point
    lacks a user_id field entirely; only uploaded chunks have one, which
    is what the retrieval-side filter (hybrid_search's user_id
    parameter) relies on to distinguish them."""
    from qdrant_client.http import models as qmodels

    sparse_model = get_sparse_model()
    texts = [c.text for c in chunks]

    dense_response = openai_client.embeddings.create(model=DENSE_EMBEDDING_MODEL, input=texts)
    dense_vectors = [d.embedding for d in dense_response.data]
    sparse_vectors = list(sparse_model.embed(texts))

    points = []
    for chunk, dense_vec, sparse_vec in zip(chunks, dense_vectors, sparse_vectors):
        payload = {
            "chunk_id": chunk.chunk_id,
            "source": chunk.source,
            "topics": chunk.topics,
            "source_id": chunk.source_id,
            "chunk_type": chunk.chunk_type,
            "chunk_index": chunk.chunk_index,
            "text": chunk.text,
            "raw_text": chunk.raw_text,
            "metadata": chunk.metadata,
            "linked_images": [],
            "user_id": chunk.metadata["user_id"],
            "session_id": chunk.metadata["session_id"],
            "document_id": chunk.metadata["document_id"],
        }
        points.append(qmodels.PointStruct(
            id=chunk.point_id,
            vector={
                DENSE_VECTOR_NAME: dense_vec,
                SPARSE_VECTOR_NAME: qmodels.SparseVector(
                    indices=sparse_vec.indices.tolist(), values=sparse_vec.values.tolist(),
                ),
            },
            payload=payload,
        ))

    qdrant_client.upsert(collection_name=TEXT_COLLECTION, points=points)
    return len(points)