"""
Neo4j connection and graph schema setup for MedRAG's medical knowledge
graph.

The graph is scoped to OpenFDA drug label data only (see
graph_ingestion.py's module docstring for why) - two node labels
(Drug, Disease) connected by one of three relationship types (TREATS,
CONTRAINDICATED_IN, CAUSES).
"""

import logging

from neo4j import GraphDatabase, Driver

logger = logging.getLogger("medrag.knowledge_graph")


def get_neo4j_driver(uri: str, user: str, password: str) -> Driver:
    """Create a Neo4j driver and verify connectivity immediately -
    unlike QdrantClient (Phase 8), where connectivity is checked
    separately via get_collections(), the neo4j driver's
    verify_connectivity() is the standard, cheap way to fail fast on a
    bad connection rather than deferring the failure to the first real
    query."""
    driver = GraphDatabase.driver(uri, auth=(user, password))
    driver.verify_connectivity()
    return driver


def setup_constraints(driver: Driver) -> None:
    """Create uniqueness constraints on node identity, keyed by
    normalized_name (lowercase, whitespace-stripped - see
    graph_ingestion.normalize_entity). Safe to call repeatedly -
    IF NOT EXISTS makes this idempotent, matching the non-destructive
    pattern used for ensure_collections() in Phase 8."""
    with driver.session() as session:
        session.run("CREATE CONSTRAINT drug_name IF NOT EXISTS FOR (d:Drug) REQUIRE d.normalized_name IS UNIQUE")
        session.run("CREATE CONSTRAINT disease_name IF NOT EXISTS FOR (dis:Disease) REQUIRE dis.normalized_name IS UNIQUE")
    logger.info("Constraints ensured (drug_name, disease_name)")