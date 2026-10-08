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

Isolation contract: the API passes the owning chat's session_id as the
retrieval user_id key. Uploaded chunks are visible only in that chat,
including after refresh and sign-in. A different chat or account cannot
retrieve them. session_id and document_id metadata also support upload
inventory, publication and deletion. Missing retrieval identity is curated-only;
full-corpus evaluation requires an explicit internal evaluation option.

"""

import io
import logging
import hashlib
import uuid
from typing import List

import pdfplumber

from medrag.processing.chunker import sentence_based_chunk
from medrag.processing.models import Chunk
from medrag.embeddings.embedder import build_batches, embed_batch_with_retry
from medrag.embeddings.qdrant_client import DENSE_VECTOR_NAME, SPARSE_VECTOR_NAME, TEXT_COLLECTION

logger = logging.getLogger("medrag.ingestion.user_upload")

MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024  # 20 MB
MAX_UPLOAD_PAGES = 100
MAX_EXTRACTED_CHARACTERS = 200000
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
            if len(pdf.pages) > MAX_UPLOAD_PAGES:
                raise UploadExtractionError(f"PDF exceeds the {MAX_UPLOAD_PAGES}-page upload limit.")
            pages_text = []
            total_characters = 0
            for page in pdf.pages:
                text = page.extract_text() or ""
                total_characters += len(text)
                if total_characters > MAX_EXTRACTED_CHARACTERS:
                    raise UploadExtractionError("PDF contains too much extracted text. Upload a smaller document.")
                pages_text.append(text)
    except UploadExtractionError:
        raise
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


def embed_and_upsert_upload_chunks(chunks: List[Chunk], qdrant_client, openai_client, collection_name=None, publish=True) -> int:
    try:
        return _embed_upload_chunks(chunks, qdrant_client, openai_client, collection_name, publish)
    except Exception:
        if chunks and publish:
            try:
                delete_upload(chunks[0].metadata["session_id"], chunks[0].metadata["document_id"], qdrant_client, collection_name)
            except Exception:
                logger.exception("Upload cleanup failed; incomplete chunks remain hidden")
        raise


def _embed_upload_chunks(chunks: List[Chunk], qdrant_client, openai_client, collection_name=None, publish=True) -> int:
    """Embed (dense + sparse, matching Phase 9's hybrid schema) and
    upsert uploaded chunks into the SAME medrag_text collection used by
    the curated corpus - a purely additive write. Every existing point
    lacks a user_id field entirely; only uploaded chunks have one, which
    is what the retrieval-side filter (hybrid_search's user_id
    parameter) relies on to distinguish them."""
    from qdrant_client.http import models as qmodels

    if not chunks:
        return 0
    batches = build_batches(chunks)
    sparse_model = get_sparse_model()
    total = 0
    for batch in batches:
        texts = [c.text for c in batch]
        dense_vectors = embed_batch_with_retry(openai_client, texts)
        sparse_vectors = list(sparse_model.embed(texts))
        if len(sparse_vectors) != len(batch):
            raise ValueError('Sparse response count does not match upload chunks')
        points = []
        for chunk, dense_vec, sparse_vec in zip(batch, dense_vectors, sparse_vectors):
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
                "upload_ready": False,
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

        qdrant_client.upsert(collection_name=collection_name or TEXT_COLLECTION, points=points, wait=True)
        total += len(points)
    if publish:
        publish_upload(chunks[0].metadata["session_id"], chunks[0].metadata["document_id"], qdrant_client, collection_name)
    return total


def upload_selector(session_id, document_id):
    from qdrant_client.http import models as qm
    return qm.Filter(must=[
        qm.FieldCondition(key="source", match=qm.MatchValue(value="user_upload")),
        qm.FieldCondition(key="session_id", match=qm.MatchValue(value=session_id)),
        qm.FieldCondition(key="document_id", match=qm.MatchValue(value=document_id)),
    ])


def publish_upload(session_id, document_id, client, collection_name=None):
    client.set_payload(collection_name=collection_name or TEXT_COLLECTION,
                       payload={"upload_ready": True}, points=upload_selector(session_id, document_id), wait=True)


def delete_upload(session_id, document_id, client, collection_name=None):
    """Delete only this session's deterministic document; never the corpus."""
    from qdrant_client.http import models as qm
    client.delete(collection_name=collection_name or TEXT_COLLECTION,
                  points_selector=qm.FilterSelector(filter=upload_selector(session_id, document_id)), wait=True)


def index_document(conn, session_id, file_bytes, filename, qdrant_client, openai_client):
    """Retry-safe indexing. Caller must hold session_operation for this session.

    Chunks stay hidden until the SQL registry commit succeeds. A retry either
    publishes a committed document or removes interrupted staging data and
    restarts using the same document ID. The filename of the first successful
    upload is retained when the identical bytes are submitted again.
    """
    from medrag.memory.db import transaction
    digest = hashlib.sha256(file_bytes).hexdigest()
    document_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"medrag-upload:{session_id}:{digest}"))
    with conn.cursor() as cur:
        cur.execute("SELECT document_id, filename, chunk_count FROM uploaded_documents WHERE session_id = %s AND content_hash = %s", (session_id, digest))
        existing = cur.fetchone()
    if existing:
        publish_upload(session_id, str(existing[0]), qdrant_client)
        return {"document_id": str(existing[0]), "filename": existing[1], "chunk_count": existing[2]}

    text = extract_text_from_pdf(file_bytes)
    chunks = chunk_user_upload(text, user_id=session_id, session_id=session_id, document_id=document_id, filename=filename)
    if not chunks:
        raise UploadExtractionError("The PDF produced no indexable chunks.")
    # Remove remnants of an earlier interrupted attempt before starting anew.
    delete_upload(session_id, document_id, qdrant_client)
    try:
        count = embed_and_upsert_upload_chunks(chunks, qdrant_client, openai_client, publish=False)
        with transaction(conn):
            with conn.cursor() as cur:
                cur.execute("INSERT INTO uploaded_documents (document_id, session_id, content_hash, filename, chunk_count) VALUES (%s, %s, %s, %s, %s)", (document_id, session_id, digest, filename, count))
    except Exception:
        try:
            delete_upload(session_id, document_id, qdrant_client)
        except Exception:
            logger.exception("Upload cleanup failed; staged chunks remain hidden and are removed on retry")
        raise
    # If this call fails, keep the committed registry. A retry republishes it
    # without paying for extraction/embedding again.
    publish_upload(session_id, document_id, qdrant_client)
    return {"document_id": document_id, "filename": filename, "chunk_count": count}
