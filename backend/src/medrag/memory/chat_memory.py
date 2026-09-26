"""
Chat memory: persists conversation sessions/messages to Postgres, and
extends Phase 14's generate_answer() with conversation history so
follow-up questions can reference earlier turns.

Core problem this module solves (Phase 16), found and fixed during
development: a follow-up question like "What are its contraindications?"
has almost no retrievable semantic content on its own. Fix: query
reformulation - before retrieval, the LLM rewrites the follow-up into a
standalone question using recent history, and that rewritten query -
not the original - drives retrieval and knowledge-graph drug detection.
The model's final answer is still generated using the ORIGINAL user
query plus full conversation history, so the response reads naturally.

Phase 19: generate_answer_with_memory() accepts an optional user_id,
passed straight through to search_with_reranking() (and therefore
hybrid_search()'s isolation filter) - this is what lets a chat actually
retrieve a user's own uploaded documents, on top of the curated corpus,
without any chance of surfacing a different user's uploads.

Phase 18 integration note: citations can only be built (Phase 15) after
this function returns the retrieved results, which only exist inside
this call - so this function returns (answer, results,
assistant_message_id), and citations are attached to the already-stored
assistant message via update_message_citations() as a separate,
post-generation step, rather than passed in upfront.
"""

import json
import logging
from typing import List, Optional

import openai
from neo4j import Driver
from psycopg2.extensions import connection as PGConnection
from psycopg2.extras import RealDictCursor
from qdrant_client import QdrantClient

from medrag.generation.generation import (
    DEFAULT_GENERATION_MODEL,
    SYSTEM_PROMPT_TEMPLATE,
    format_context,
    find_mentioned_drug,
    get_all_known_drug_names,
    get_graph_facts_for_drug_curated,
    format_graph_facts,
)
from medrag.retrieval.reranking import search_with_reranking

logger = logging.getLogger("medrag.memory")

DEFAULT_BOUNDED_TURNS = 8

REFORMULATION_PROMPT = """Given the conversation history and a follow-up question, rewrite the follow-up question as a standalone question that includes all necessary context from the history. Do not answer the question - only rewrite it.

If the follow-up question is already standalone (doesn't depend on prior context), return it unchanged.

Conversation history:
{history}

Follow-up question: {query}

Standalone question:"""


def create_session(conn: PGConnection, title: Optional[str] = None, user_id: Optional[str] = None) -> str:
    """Create a new chat session, return its session_id. user_id (Phase
    19) groups multiple sessions/chats under the same person - passing
    None keeps a session usable but without shared upload access across
    other sessions."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "INSERT INTO sessions (title, user_id) VALUES (%s, %s) RETURNING session_id",
            (title, user_id),
        )
        return str(cur.fetchone()["session_id"])


def session_exists(conn: PGConnection, session_id: str) -> bool:
    """Check whether a session_id actually corresponds to a created
    session, distinct from an empty (but real) session's history."""
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM sessions WHERE session_id = %s", (session_id,))
        return cur.fetchone() is not None


def get_session_user_id(conn: PGConnection, session_id: str) -> Optional[str]:
    """Look up the user_id a session belongs to (Phase 19) - used by
    the /chat and /documents endpoints to apply upload isolation
    without requiring the caller to separately track and re-send it on
    every request."""
    with conn.cursor() as cur:
        cur.execute("SELECT user_id FROM sessions WHERE session_id = %s", (session_id,))
        row = cur.fetchone()
        return row[0] if row else None


def add_message(
    conn: PGConnection,
    session_id: str,
    role: str,
    content: str,
    citations: Optional[list] = None,
) -> str:
    """Append a message to a session, and bump the session's updated_at
    timestamp so session lists can be ordered by recency."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            INSERT INTO messages (session_id, role, content, citations)
            VALUES (%s, %s, %s, %s)
            RETURNING message_id
            """,
            (session_id, role, content, json.dumps(citations) if citations else None),
        )
        message_id = cur.fetchone()["message_id"]
        cur.execute("UPDATE sessions SET updated_at = now() WHERE session_id = %s", (session_id,))
    return str(message_id)


def update_message_citations(conn: PGConnection, message_id: str, citations: list) -> None:
    """Attach citations to an already-stored message - see module
    docstring's Phase 18 integration note for why this is a separate
    step rather than passed in upfront."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE messages SET citations = %s WHERE message_id = %s",
            (json.dumps(citations) if citations else None, message_id),
        )


def get_session_history(conn: PGConnection, session_id: str, limit: Optional[int] = None) -> List[dict]:
    """Load a session's messages in chronological order. limit=None
    returns the full history; an integer limit returns only the most
    recent N messages (e.g. for a bounded generation window)."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        if limit is None:
            cur.execute(
                "SELECT * FROM messages WHERE session_id = %s ORDER BY created_at ASC",
                (session_id,),
            )
        else:
            cur.execute(
                """
                SELECT * FROM (
                    SELECT * FROM messages WHERE session_id = %s
                    ORDER BY created_at DESC LIMIT %s
                ) sub ORDER BY created_at ASC
                """,
                (session_id, limit),
            )
        return [dict(row) for row in cur.fetchall()]


def build_message_history(conn: PGConnection, session_id: str, bounded_turns: int = DEFAULT_BOUNDED_TURNS) -> List[dict]:
    """Load recent messages formatted for an OpenAI chat call, bounded
    to the last N turns. Citations are stripped - the model only needs
    the conversational text."""
    messages = get_session_history(conn, session_id, limit=bounded_turns * 2)
    return [{"role": m["role"], "content": m["content"]} for m in messages]


def reformulate_query(
    conn: PGConnection,
    openai_client: openai.OpenAI,
    session_id: str,
    query: str,
    model: str = DEFAULT_GENERATION_MODEL,
) -> str:
    """Rewrite a follow-up question into a standalone query using
    conversation history, so retrieval and knowledge-graph drug
    detection have meaningful content to work with."""
    history_messages = build_message_history(conn, session_id, bounded_turns=4)
    if not history_messages:
        return query

    history_text = "\n".join(f"{m['role']}: {m['content']}" for m in history_messages)

    response = openai_client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": REFORMULATION_PROMPT.format(history=history_text, query=query)}],
    )
    return response.choices[0].message.content.strip()


def generate_answer_with_memory(
    query: str,
    session_id: str,
    conn: PGConnection,
    qdrant_client: QdrantClient,
    openai_client: openai.OpenAI,
    neo4j_driver: Optional[Driver] = None,
    model: str = DEFAULT_GENERATION_MODEL,
    bounded_turns: int = DEFAULT_BOUNDED_TURNS,
    user_id: Optional[str] = None,
):
    """Full history-aware pipeline: reformulate the query for retrieval
    purposes -> hybrid retrieval + reranking + optional knowledge graph
    enrichment (using the reformulated query, and user_id-filtered per
    Phase 19 if provided) -> generation (using the ORIGINAL query + full
    conversation history) -> persist both turns.

    Returns (answer, results, assistant_message_id)."""
    retrieval_query = reformulate_query(conn, openai_client, session_id, query, model=model)

    results = search_with_reranking(
        qdrant_client, retrieval_query,
        candidate_pool_size=20, top_n=5, user_id=user_id,
    )
    context = format_context(results)

    graph_section = ""
    if neo4j_driver is not None:
        known_drug_names = get_all_known_drug_names(neo4j_driver)
        mentioned_drug = find_mentioned_drug(retrieval_query, known_drug_names)
        if mentioned_drug:
            facts = get_graph_facts_for_drug_curated(neo4j_driver, mentioned_drug)
            graph_section = format_graph_facts(facts)

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(context=context, graph_section=graph_section)
    history_messages = build_message_history(conn, session_id, bounded_turns=bounded_turns)

    messages = (
        [{"role": "system", "content": system_prompt}]
        + history_messages
        + [{"role": "user", "content": query}]
    )

    response = openai_client.chat.completions.create(model=model, messages=messages)
    answer = response.choices[0].message.content

    add_message(conn, session_id, "user", query)
    assistant_message_id = add_message(conn, session_id, "assistant", answer)

    return answer, results, assistant_message_id