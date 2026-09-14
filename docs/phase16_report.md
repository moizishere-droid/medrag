# Phase 16: Chat Memory (PostgreSQL) — Report

## Phase Objective

Add persistent, session-scoped conversation memory: store chat sessions and messages in PostgreSQL, allow a conversation to be resumed later, and extend Phase 14's generation pipeline so follow-up questions can correctly reference earlier turns rather than being answered in isolation.

## What Was Built

- **A dedicated, isolated Postgres database** (`medrag_chat`, container `medrag_postgres`, host port 5433) — kept fully separate from any other project's database.
- **`sessions` / `messages` schema** — sessions hold conversation metadata; messages hold ordered turns, with an assistant message's resolved citations (Phase 15) stored alongside it as JSONB.
- **`create_session()` / `add_message()` / `get_session_history()`** — core storage operations.
- **`build_message_history()`** — loads a bounded window of recent turns formatted for an LLM call.
- **`reformulate_query()`** — rewrites a follow-up question into a standalone query using conversation history, before retrieval runs.
- **`generate_answer_with_memory()`** — the full history-aware pipeline: reformulate → retrieve/rerank/graph-enrich (using the reformulated query) → generate (using the original query + full history) → persist both turns.
- **`backend/src/medrag/memory/`** — new package (`db.py`, `chat_memory.py`, `__init__.py`).

## Key Design Decisions

1. **A dedicated Postgres instance, isolated from other projects.** Rather than reusing an existing Postgres container from another portfolio project, a fresh container on a distinct host port (5433, avoiding a collision with the other project's 5432) keeps the two projects' data fully separate.
2. **Bounded history window for generation (default: last 8 turns / 16 messages), full history always stored regardless.** This keeps prompt size and token cost predictable as a conversation grows long, while never losing data — resuming a session for display always has access to everything that was ever said, independent of what any single generation call used as context.
3. **Citations are persisted as JSONB alongside the assistant message, not reconstructed later.** Since Phase 15 already produces a structured citation list per answer, storing it directly with the message means a resumed session can display the exact citations that were shown the first time, without re-running retrieval or citation resolution.
4. **A genuine architectural gap was found and fixed, not just tuned around.** Directly testing a real follow-up question ("What are its contraindications?" after a prior turn discussing metformin) surfaced incorrect behavior: the answer claimed the context lacked the information, despite the fact being available and previously validated. Root-caused to a layering problem, not a language-understanding problem — retrieval (vector search) and knowledge-graph drug detection both run on the raw new query *before* the LLM ever sees any conversation history, so a pronoun-only follow-up has essentially no retrievable content, even though the LLM itself, given history, could correctly resolve what "its" referred to when composing its final answer.
5. **Query reformulation as the fix, applied only to the retrieval path, not the generation path.** Before retrieval, a separate LLM call rewrites the follow-up into a standalone question using recent history (e.g. "What are its contraindications?" → "What are the contraindications of metformin?"). This reformulated query drives retrieval and knowledge-graph drug detection. The final answer, however, is still generated using the user's *original* question plus full conversation history — so the response reads as a natural reply to what was actually asked, not an answer to a robotically-rewritten question the user never typed.
6. **`reformulate_query()` uses a small, separate history window (4 turns)**, distinct from the larger window used for final generation — reformulation only needs recent context to resolve a pronoun or implicit reference, not the entire bounded generation window.

## Results

- **Schema and storage operations verified directly**: a test session with two manually-added messages round-tripped correctly through storage, including proper JSON citation serialization/deserialization.
- **The core bug was confirmed and diagnosed precisely before fixing**: a direct test isolated the problem to retrieval/drug-detection receiving an unreformulated query, producing essentially unrelated results (a diuretic, two unrelated cancer drugs, an anesthetic kit) for a metformin-related follow-up.
- **The reformulation fix was verified to resolve the exact failure case**: the same follow-up question, run through the corrected pipeline, correctly returned metformin's real, previously-validated contraindications (renal impairment, hypersensitivity, metabolic acidosis, diabetic ketoacidosis).
- **Production `generate_answer_with_memory()` verified to exactly reproduce the notebook's fixed result** via a full-stack integration test (Postgres + Qdrant + Neo4j + OpenAI together).

## Challenges & Solutions

- **A real, non-obvious architectural gap in history-aware RAG was found through direct testing rather than assumed away.** The natural first implementation (simply appending history to the LLM's message list) is intuitive but incomplete for a RAG system specifically, since retrieval itself is a separate step that also needs to understand context — a distinction that's easy to miss without testing an actual multi-turn conversation with a genuine pronoun-based follow-up. This is a valuable, demonstrable finding for a portfolio project: identifying and fixing a subtle, realistic failure mode in conversational RAG architecture, not just wiring pieces together.

## Files Created

- `backend/src/medrag/memory/__init__.py`
- `backend/src/medrag/memory/db.py` (`get_postgres_connection`, `ensure_schema`)
- `backend/src/medrag/memory/chat_memory.py` (`create_session`, `add_message`, `get_session_history`, `build_message_history`, `reformulate_query`, `generate_answer_with_memory`)
- `notebooks/phase16_chat_memory.ipynb`

No new runner script — chat memory operations are invoked per-request (eventually by the Phase 18 FastAPI layer), not a batch job.