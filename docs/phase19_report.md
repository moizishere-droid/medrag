# Phase 19: User Document Upload Pipeline

## Objective

Extend MedRAG so a user can upload their own PDF documents and have the
RAG system answer questions using both the curated corpus (PubMed, WHO,
OpenFDA) and their uploaded content, without one session's uploads ever
being visible to any other session.

## What Was Built

- **Extraction**: `medrag/ingestion/user_upload.py` — plain page-by-page
  PDF text extraction via pdfplumber, deliberately simpler than WHO's
  pipeline (no header/footer stripping, no table-region detection — an
  arbitrary uploaded PDF has no known structure to exploit).
- **Chunking**: reuses Phase 5's `sentence_based_chunk()` directly
  (already source-agnostic); each chunk is tagged with the uploading
  session's own `session_id`, plus a `document_id` distinguishing
  multiple uploads within the same session.
- **Embedding/storage**: dense (text-embedding-3-small) + sparse
  (Qdrant/bm25) vectors, upserted additively into the existing
  `medrag_text` collection — no new collection, no schema change to
  existing points.
- **Retrieval isolation**: `hybrid_search.py`'s `build_user_filter()`
  applies a should-filter ("point has no session-scoping field at all"
  OR "point's session-scoping field matches this session") to *both*
  the dense and sparse legs of hybrid search, before RRF fusion.
- **New API endpoint**: `POST /sessions/{session_id}/documents` —
  validates file type/size, extracts, chunks, embeds, upserts, scoped
  to `session_id` directly.

## Key Design Decisions

**Isolation scope: session-only.** Every uploaded document is tagged
with the `session_id` of the session it was uploaded in, and retrieval
is filtered on that same value. This keeps the isolation boundary
simple and requires no separate identity concept, no login, and no
client-side persistence mechanism: a session already has a unique,
server-issued ID the moment it's created, so that ID doubles as the
isolation key with no extra moving parts.

**Stated tradeoff.** Opening a new chat session starts with no access
to documents uploaded in a previous session, even from the same
person/browser. This differs from ChatGPT/Claude-style persistent
uploads across conversations, which requires real user accounts to do
correctly. Given this project explicitly scopes out authentication
(see Phase 18), building a substitute identity mechanism (a manually
typed ID, or an auto-generated one persisted via browser storage) would
add real complexity and its own reliability concerns for a benefit that
doesn't change what the feature is meant to demonstrate — grounded,
isolated retrieval over user-supplied content. Session-scoping is the
simplest mechanism that satisfies the core requirement (no cross-user
leakage) without that overhead.

**Extraction scope tradeoff vs. WHO's pipeline.** No header/footer
removal, no table-aware extraction, no image extraction for uploads —
a real, accepted limitation given uploaded PDFs have no known layout
structure to exploit, unlike the curated WHO corpus.

## Results

- Notebook validation: real PDF (`Diabetes_Mellitus_Type_2.pdf`, 8
  pages, 11 chunks at target_tokens=300) — confirmed additive upsert
  with no disruption to the existing 22,696-point baseline, and
  session-scoped retrieval isolation confirmed correct.
- Production integration verified via `TestClient`: two independently
  created sessions, upload to session A only, chat in session A
  correctly retrieves and cites the upload (citation `title` resolved
  to the real filename), chat in session B (a separate session)
  returns zero trace of it.
- Verified again against a real running `uvicorn` server with a genuine
  multipart file upload and `/chat` call, confirming the same isolation
  behavior outside of `TestClient`.
- Collection returned to exact baseline (22696) after every round of
  test cleanup.

## Challenges & Solutions

**Notebook cleanup fragility.** Deleting test upload points by
`document_id` silently failed to catch an earlier batch after a cell
was re-run and generated a new `document_id`, orphaning the old batch.
Found via re-scrolling and comparing exact counts rather than trusting
the delete call blindly. Lesson: always re-verify count after a
cleanup delete, never assume it worked.

**Citation system had no branch for the new source type.** Phase 15's
`get_display_info()` only handled `"who"`, `"pubmed"`, `"openfda"` —
`"user_upload"` silently fell through to a generic `"Unknown source"`
fallback. Fixed by adding an explicit `user_upload` branch using the
chunk's `metadata.filename` as the title, with `url=None` (uploaded
documents are private, no public URL makes sense).

**Stale port listener caused a debugging detour.** After the citation
fix, the running server kept returning old behavior despite the
corrected code being confirmed correct and singular on disk. Root
cause: two orphaned uvicorn processes were both bound to port 8000
from earlier test sessions; `netstat` continued reporting them as
`LISTENING` even after `taskkill` reported both PIDs as already gone —
a stale OS-level socket table entry, not a live process. Resolved by
running on a fresh port (8001). Lesson: when code is verified correct
on disk but behavior doesn't change, check for port/process ambiguity
before re-suspecting the code.

## Files Created

- `medrag/ingestion/user_upload.py` (new)
- `medrag/retrieval/hybrid_search.py` (session-scoped isolation filter,
  applied to both dense and sparse legs)
- `medrag/retrieval/reranking.py` (pass-through of the isolation key)
- `medrag/memory/db.py`, `medrag/memory/chat_memory.py` (supporting
  session lookup functions)
- `medrag/citations/citations.py` (patched — `user_upload` branch in
  `get_display_info()`)
- `medrag/api/models.py` (`UploadDocumentResponse`)
- `medrag/api/main.py` (new `POST /sessions/{session_id}/documents`
  endpoint; `/chat` and upload both scoped by `session_id`)
- `backend/scripts/verify_phase19.py` (TestClient-based end-to-end
  verification script)