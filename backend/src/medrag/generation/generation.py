"""
LLM answer generation: takes a reranked set of retrieved chunks (Phase
11), optionally enriches them with structured facts from the OpenFDA
knowledge graph (Phase 13), and generates a grounded, cited answer in
the same language as the query.

Model: gpt-4.1-nano by default - chosen for cost (this is a student
portfolio project, not a funded production deployment) over the
originally-planned gpt-4-turbo, which was fully retired from the
OpenAI API in 2026 well after the project's initial scoping. Newer
flagship families (GPT-5.6, GPT-6) were tested and found to not be
available on this project's OpenAI account/usage tier; gpt-4.1-nano
was confirmed available and is OpenAI's purpose-built low-cost tier.
A stronger model (e.g. gpt-5.2, confirmed available on this account)
is a documented, tested fallback if generation quality on a given
query proves inadequate - swap via the `model` parameter.

Core design principle: the model must be grounded and honest about
what it doesn't know, not fluent regardless of whether the retrieved
context actually supports an answer. This was directly validated: a
query with known weak corpus coverage (see Phase 10/11's diagnostic
query) correctly produced "the context does not provide specific
details..." rather than a plausible-sounding answer drawn from the
model's own training knowledge.

Citations here are a lightweight, provisional mechanism (bracketed
numbers referencing the context block a claim came from) - Phase 15
is responsible for formalizing and rendering citations properly; this
module only needs to get the model to consistently produce a taggable
reference.
"""

import logging
from typing import List, Optional

import openai
from neo4j import Driver
from qdrant_client import QdrantClient

from medrag.retrieval.reranking import search_with_reranking

logger = logging.getLogger("medrag.generation")

DEFAULT_GENERATION_MODEL = "gpt-4.1-nano"
DEFAULT_CANDIDATE_POOL_SIZE = 20
DEFAULT_TOP_N = 5
DEFAULT_MAX_CAUSES = 8

SYSTEM_PROMPT_TEMPLATE = """You are a medical information assistant. Answer the user's question using ONLY the information in the provided context below. Do not use any outside knowledge.

If the context does not contain enough information to answer the question, say so plainly - do not guess or fill gaps with your own knowledge.

The context below is in English. Detect the language of the user's question and respond in THAT SAME language, translating the relevant information from the English context as needed. If the question is in English, respond in English.

After each claim or statement in your answer, add a bracketed citation referencing which numbered context block it came from, e.g. "ACE inhibitors can cause dry cough [1]." If a claim is supported by multiple sources, cite all of them, e.g. [1][3].

{graph_section}

Context:
{context}
"""

_known_drug_names_cache: Optional[List[str]] = None


def format_context(results: List[dict]) -> str:
    """Format hybrid_search/reranking results into a numbered context
    block, one block per chunk, labeled by source."""
    blocks = []
    for i, r in enumerate(results, 1):
        blocks.append(f"[{i}] (source: {r['payload']['source']})\n{r['payload']['raw_text']}")
    return "\n\n".join(blocks)


def get_all_known_drug_names(neo4j_driver: Driver, use_cache: bool = True) -> List[str]:
    """List every Drug node's display name from the knowledge graph.
    Cached at module level by default, since the drug list only changes
    when Phase 13's ingestion is re-run - not on every query. Pass
    use_cache=False to force a fresh read (e.g. after re-running graph
    ingestion in the same process)."""
    global _known_drug_names_cache
    if use_cache and _known_drug_names_cache is not None:
        return _known_drug_names_cache

    with neo4j_driver.session() as session:
        result = session.run("MATCH (d:Drug) RETURN d.name AS name")
        names = [record["name"] for record in result]

    _known_drug_names_cache = names
    return names


def find_mentioned_drug(query: str, known_drug_names: List[str]) -> Optional[str]:
    """Simple substring match against known drug names - not NER, since
    the exact canonical name list already exists from the knowledge
    graph itself, which is more reliable than re-extracting a drug name
    from the query text."""
    query_lower = query.lower()
    for drug_name in known_drug_names:
        if drug_name.lower() in query_lower:
            return drug_name
    return None


def get_graph_facts_for_drug(neo4j_driver: Driver, drug_name: str) -> List[dict]:
    """Query Neo4j for all known relationships for a drug, matched by
    normalized (lowercase) name - same normalization used during Phase
    13 ingestion."""
    normalized = drug_name.strip().lower()
    with neo4j_driver.session() as session:
        result = session.run(
            """
            MATCH (d:Drug {normalized_name: $name})-[rel]->(dis:Disease)
            RETURN d.name AS drug, type(rel) AS relationship, dis.name AS disease
            """,
            name=normalized,
        )
        return [dict(record) for record in result]


def get_graph_facts_for_drug_curated(
    neo4j_driver: Driver,
    drug_name: str,
    max_causes: int = DEFAULT_MAX_CAUSES,
) -> List[dict]:
    """Curated version of get_graph_facts_for_drug, fixing two issues
    found by inspecting real output during Phase 14 development:

    1. A disease can appear under both TREATS and CAUSES for the same
       drug (e.g. metformin CAUSES/TREATS "type 2 diabetes mellitus") -
       a direct contradiction traced to residual NER noise from Phase
       13 (the same short-ambiguous-misfire limitation documented
       there). Resolved by dropping the disease from CAUSES whenever it
       also appears under TREATS, since indications_and_usage is the
       more authoritative, lower-noise source section.
    2. A drug can have dozens of listed adverse effects - including all
       of them bloats the prompt and buries the higher-value TREATS/
       CONTRAINDICATED_IN facts. CAUSES is capped at max_causes; TREATS
       and CONTRAINDICATED_IN are never capped (both are typically low-
       volume and high clinical importance). Note this cap is a
       practical volume control, not a principled noise filter - some
       remaining noise entities (e.g. malformed spans) may still appear
       within the capped set."""
    facts = get_graph_facts_for_drug(neo4j_driver, drug_name)

    treats_diseases = {f["disease"].lower() for f in facts if f["relationship"] == "TREATS"}
    treats = [f for f in facts if f["relationship"] == "TREATS"]
    contraindicated = [f for f in facts if f["relationship"] == "CONTRAINDICATED_IN"]
    causes = [
        f for f in facts
        if f["relationship"] == "CAUSES" and f["disease"].lower() not in treats_diseases
    ]

    return treats + contraindicated + causes[:max_causes]


def format_graph_facts(facts: List[dict]) -> str:
    if not facts:
        return ""
    lines = [f"- {f['drug']} {f['relationship']} {f['disease']}" for f in facts]
    return (
        "Verified structured facts from the medical knowledge graph:\n"
        + "\n".join(lines)
        + "\n\nTreat the above as verified, high-confidence facts - if the "
        "retrieved context below conflicts with them, prioritize these facts."
    )


def generate_answer(
    query: str,
    qdrant_client: QdrantClient,
    openai_client: openai.OpenAI,
    neo4j_driver: Optional[Driver] = None,
    model: str = DEFAULT_GENERATION_MODEL,
    candidate_pool_size: int = DEFAULT_CANDIDATE_POOL_SIZE,
    top_n: int = DEFAULT_TOP_N,
) -> str:
    """Full pipeline: hybrid retrieval + reranking (Phase 10/11) ->
    optional knowledge graph enrichment (Phase 13, only when the query
    mentions a known drug and neo4j_driver is provided) -> grounded,
    cited, language-matching generation.

    neo4j_driver is optional: pass None to skip knowledge graph
    integration entirely (e.g. if Neo4j isn't running, or for a query
    type where graph facts aren't relevant)."""
    results = search_with_reranking(
        qdrant_client, query,
        candidate_pool_size=candidate_pool_size,
        top_n=top_n,
    )
    context = format_context(results)

    graph_section = ""
    if neo4j_driver is not None:
        known_drug_names = get_all_known_drug_names(neo4j_driver)
        mentioned_drug = find_mentioned_drug(query, known_drug_names)
        if mentioned_drug:
            facts = get_graph_facts_for_drug_curated(neo4j_driver, mentioned_drug)
            graph_section = format_graph_facts(facts)

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(context=context, graph_section=graph_section)

    response = openai_client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query},
        ],
    )
    return response.choices[0].message.content