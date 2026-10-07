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

The API holds a database-backed session lock across generation and persists
the user message, assistant message and resolved citations in one SQL
transaction. This function returns (answer, results, assistant_message_id)
so callers can attach citations before committing their outer transaction.
Standalone callers also get atomic persistence of the message pair.
"""

import json
import uuid
import logging
import re
from time import perf_counter
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
from medrag.memory.db import transaction
from medrag.memory.session_titles import title_from_query
from medrag.generation.language import language_instruction, complete_in_query_language
from medrag.topics import TOPICS

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
    try:
        session_id = str(uuid.UUID(str(session_id)))
    except (ValueError, TypeError, AttributeError):
        return False
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM sessions WHERE session_id = %s", (session_id,))
        return cur.fetchone() is not None


def title_session_from_first_query(conn, session_id, query):
    """Name only an untitled chat's first successful turn, inside its transaction."""
    with conn.cursor() as cur:
        cur.execute("""UPDATE sessions SET title = %s WHERE session_id = %s
            AND (title IS NULL OR btrim(title) = '')
            AND NOT EXISTS (SELECT 1 FROM messages WHERE session_id = %s)""",
                    (title_from_query(query), session_id, session_id))


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
        cur.execute("UPDATE sessions SET updated_at = clock_timestamp() WHERE session_id = %s", (session_id,))
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
                "SELECT * FROM messages WHERE session_id = %s ORDER BY created_at ASC, message_sequence ASC",
                (session_id,),
            )
        else:
            cur.execute(
                """
                SELECT * FROM (
                    SELECT * FROM messages WHERE session_id = %s
                    ORDER BY created_at DESC, message_sequence DESC LIMIT %s
                ) sub ORDER BY created_at ASC, message_sequence ASC
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

def list_sessions(conn, user_id=None) -> list[dict]:
    """Return all sessions, most recently updated first."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT session_id, title, created_at, updated_at
            FROM sessions
            """ + ("WHERE user_id = %s " if user_id is not None else "") + """
            ORDER BY updated_at DESC
            """
            , (user_id,) if user_id is not None else None
        )
        rows = cur.fetchall()
        columns = [desc[0] for desc in cur.description]
        return [dict(zip(columns, row)) for row in rows]

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
    explicit_topic = any(re.search(r"(?<!\w)" + re.escape(topic) + r"(?!\w)", query, re.I) for topic in TOPICS)
    contextual = re.search(r"\b(it|its|they|them|their|this|that|these|those|previous|above|same|discussed|also)\b", query, re.I)
    standalone = bool(explicit_topic and not contextual and re.match(r"\s*(what (is|are)|explain|describe|define)\b", query, re.I))
    if not history_messages or standalone:
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
    started = perf_counter()
    retrieval_query = reformulate_query(conn, openai_client, session_id, query, model=model)
    reformulated = perf_counter()

    results = search_with_reranking(
        qdrant_client, retrieval_query,
        candidate_pool_size=20, top_n=5, user_id=user_id,
    )
    context = format_context(results)
    retrieved = perf_counter()

    graph_section = ""
    if neo4j_driver is not None:
        known_drug_names = get_all_known_drug_names(neo4j_driver)
        mentioned_drug = find_mentioned_drug(retrieval_query, known_drug_names)
        if mentioned_drug:
            facts = get_graph_facts_for_drug_curated(neo4j_driver, mentioned_drug)
            graph_section = format_graph_facts(facts)

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(context=context, graph_section=graph_section) + language_instruction(query)
    history_messages = build_message_history(conn, session_id, bounded_turns=bounded_turns)

    messages = (
        [{"role": "system", "content": system_prompt}]
        + history_messages
        + [{"role": "user", "content": query}]
    )
    prepared = perf_counter()

    answer = complete_in_query_language(openai_client, model, messages, query)
    generated = perf_counter()
    logger.info(
        "Chat pipeline seconds: reformulation=%.3f retrieval=%.3f graph_history=%.3f generation=%.3f",
        reformulated - started, retrieved - reformulated,
        prepared - retrieved, generated - prepared,
    )

    with transaction(conn):
        add_message(conn, session_id, "user", query)
        assistant_message_id = add_message(conn, session_id, "assistant", answer)

    return answer, results, assistant_message_id
