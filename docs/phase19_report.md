# Phase 19: User Document Upload Pipeline

## Objective

Extend MedRAG so a user can upload their own PDF documents and have the
RAG system answer questions using both the curated corpus (PubMed, WHO,
OpenFDA) and their uploaded content — while keeping one user's uploads
completely invisible to every other user, and visible across all of
that same user's own chat sessions (matching the multi-chat behavior of
ChatGPT/Claude, not a single-session-only model).

## What Was Built

- **Extraction**: `medrag/ingestion/user_upload.py` — plain page-by-page
  PDF text extraction via pdfplumber, deliberately simpler than WHO's
  pipeline (no header/footer stripping, no table-region detection — an
  arbitrary uploaded PDF has no known structure to exploit).
- **Chunking**: reuses Phase 5's `sentence_based_chunk()` directly
  (already source-agnostic); new tagging wraps each chunk with three
  identifiers — `user_id` (the real retrieval-isolation boundary),
  `session_id` (citation display only), `document_id` (distinguishes
  multiple uploads from the same user).
- **Embedding/storage**: dense (text-embedding-3-small) + sparse
  (Qdrant/bm25) vectors, upserted additively into the existing
  `medrag_text` collection — no new collection, no schema change to
  existing points.
- **Retrieval isolation**: `hybrid_search.py`'s new `build_user_filter()`
  applies a should-filter ("point has no `user_id` field at all" OR
  "point's `user_id` matches this user") to *both* the dense and sparse
  legs of hybrid search, before RRF fusion.
- **Chat memory integration**: `sessions` table gets a new `user_id`
  column (safe `ALTER TABLE ADD COLUMN IF NOT EXISTS` migration);
  `get_session_user_id()` looks it up so `/chat` doesn't require the
  caller to separately resend it.
- **New API endpoint**: `POST /sessions/{session_id}/documents` —
  validates file type/size, extracts, chunks, embeds, upserts, all
  scoped to the session's `user_id`. Returns 400 if the session has no
  `user_id` (upload isolation requires one).

## Key Design Decisions

**session_id → user_id pivot.** The initial design scoped uploads to
`session_id` (one chat, one upload, invisible to all other chats). This
was found insufficient once multi-chat-per-person behavior was
clarified as the actual requirement: a user with two open chat tabs
should see the same uploaded document in both, while a different person
should see neither. Redesigned around a lightweight `user_id` (not real
auth — a client-generated identifier, to be produced by Phase 20's
frontend). Both the session_id-only and user_id versions were built and
tested in the notebook before the user_id version was carried into
production; the session_id-only version was found to genuinely fail
the "second open chat" case before being replaced, not discarded on
theory alone.

**Additive-write safety.** Every upload writes into the same
`medrag_text` collection the curated corpus lives in, rather than a
separate collection — this keeps retrieval logic (dense+sparse+RRF)
identical for both source types. Given the risk of an additive write
silently polluting the corpus, every test stage (notebook, TestClient,
real server) explicitly verified the collection's exact point count
before and after, confirming zero unintended side effects each time.

**Extraction scope tradeoff vs. WHO's pipeline.** Deliberately accepted
scope reduction: no header/footer removal, no table-aware extraction,
no image extraction for uploads. A real, stated tradeoff for a feature
handling arbitrary user PDFs rather than a fixed curated corpus with
known layout patterns.

## Results

- Notebook validation: real PDF (`Diabetes_Mellitus_Type_2.pdf`, 8
  pages, 11 chunks at target_tokens=300) — confirmed additive upsert
  (22696 → 22707, exactly +11), user_id-filtered retrieval correct
  across all three isolation scenarios (same user/different session
  sees it; different user sees nothing; mixed queries blend both
  source types correctly).
- Production integration: all 5 drafted files (`user_upload.py`,
  `hybrid_search.py`, `reranking.py`, `db.py`, `chat_memory.py`) placed
  and verified in the real project — first via `TestClient` (with
  lifespan), then via a real running `uvicorn` server with a genuine
  multipart file upload and `/chat` call.
- End-to-end confirmed on the real server: upload → 11 chunks → chat
  question answered correctly and grounded in the uploaded PDF →
  citation correctly resolved to `"Diabetes_Mellitus_Type_2.pdf"` →
  a second session with a different `user_id` retrieved zero trace of
  the upload.
- Collection returned to exact baseline (22696) after all test cleanup.

## Challenges & Solutions

**Notebook cleanup fragility.** Deleting test upload points by
`document_id` silently failed to catch an earlier batch after the cell
was re-run and generated a new `document_id` — the old batch was
orphaned under a stale variable reference. Found via re-scrolling and
comparing exact counts rather than trusting the delete call blindly.
Lesson: always re-verify count after a cleanup delete, never assume it
worked.

**Citation system had no branch for the new source type.** Phase 15's
`get_display_info()` only handled `"who"`, `"pubmed"`, `"openfda"` —
`"user_upload"` silently fell through to a generic `"Unknown source"`
fallback. Found during real-server testing (not caught by TestClient
alone, since the specific query/answer path exercised there didn't
surface it until closer inspection of the citation object). Fixed by
adding an explicit `user_upload` branch using the chunk's
`metadata.filename` as the title, with `url=None` (uploaded documents
are private, no public URL makes sense).

**Stale port listener caused a debugging detour.** After fixing the
citation bug, the running server kept returning the old, unfixed
behavior despite the corrected code being confirmed correct on disk,
confirmed as the only copy on the filesystem, and confirmed as the
exact file Python was importing (`__file__` check). Root cause: two
orphaned uvicorn processes were both bound to port 8000 from earlier
test sessions; `netstat` continued reporting them as `LISTENING` even
after `taskkill` reported both PIDs as already gone — a stale OS-level
socket table entry, not a live process. Resolved by running the server
on a fresh port (8001) instead of continuing to fight the ambiguous
state on 8000. Lesson: when code is verified correct on disk but
behavior doesn't change, check for port/process ambiguity before
re-suspecting the code itself — and don't trust `netstat` alone as
proof a process is still alive.

## Files Created

- `medrag/ingestion/user_upload.py` (new)
- `medrag/retrieval/hybrid_search.py` (replaced — added `user_id` filter
  applied to both dense and sparse legs)
- `medrag/retrieval/reranking.py` (replaced — `user_id` pass-through)
- `medrag/memory/db.py` (replaced — `user_id` column, migration-safe)
- `medrag/memory/chat_memory.py` (replaced — `get_session_user_id()`,
  `user_id` threaded through `create_session()` /
  `generate_answer_with_memory()`)
- `medrag/citations/citations.py` (patched — new `user_upload` branch
  in `get_display_info()`)
- `medrag/api/models.py` (patched — `user_id` on `CreateSessionRequest`,
  new `UploadDocumentResponse`)
- `medrag/api/main.py` (patched — `user_id` wired into `/sessions` and
  `/chat`, new `POST /sessions/{session_id}/documents` endpoint)
- `backend/scripts/verify_phase19.py` (new — TestClient-based
  end-to-end verification script)