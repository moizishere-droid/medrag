"""
Runner script: extracts drug-disease relationships from all OpenFDA
chunks and writes them to Neo4j as a knowledge graph.

Run from the backend/ folder, same convention as other run_*.py scripts:
    cd backend
    python scripts/run_graph_ingestion.py

Scoped to OpenFDA only - see graph_ingestion.py's module docstring for
why WHO/PubMed relationship extraction was deliberately excluded from
this phase.

Reads:
  - OpenFDA chunks (Phase 6, data/processed/chunks/openfda/)
"""

import logging
import sys
from pathlib import Path


def find_project_root(marker: str = "backend", start: Path = None) -> Path:
    """Walk upward from `start` (or this file's location) until a folder
    containing `marker` is found. Anchors all paths below to the real
    project root regardless of which directory the script is invoked
    from - a plain relative path like "data/processed/chunks" silently
    only works when run from one specific directory, which caused this
    script to load 0 chunks without erroring when run from backend/
    rather than the project root."""
    current = (start or Path(__file__).resolve()).parent
    for candidate in [current, *current.parents]:
        if (candidate / marker).is_dir():
            return candidate
    raise RuntimeError(f"Could not find a '{marker}' folder above {current}")


PROJECT_ROOT = find_project_root()

# Ensure backend/ itself is on sys.path, not just backend/scripts/ (which
# Python adds automatically as the running script's own directory).
# config/ lives directly under backend/, one level up from scripts/, so
# without this, `from config.settings import settings` fails no matter
# how the script is invoked.
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from config.settings import settings
from medrag.knowledge_graph.neo4j_client import get_neo4j_driver, setup_constraints
from medrag.knowledge_graph.graph_ingestion import (
    extract_relationships_from_chunk,
    aggregate_relationships,
    write_relationships_batched,
)
from medrag.processing.storage import load_chunks

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("medrag.knowledge_graph")

CHUNKS_DIR = str(PROJECT_ROOT / "data" / "processed" / "chunks")


def load_all_openfda_chunks(chunks_dir: str) -> list:
    """Load every saved OpenFDA topic file, deduped by chunk_id - same
    pattern used for PubMed/OpenFDA loading in Phase 8/9's ingestion
    scripts, since OpenFDA chunks are saved per-topic with shared drugs
    duplicated identically across topic files."""
    source_dir = Path(chunks_dir) / "openfda"
    seen_ids = set()
    chunks = []
    for filepath in sorted(source_dir.glob("*.jsonl")):
        topic = filepath.stem
        for chunk in load_chunks(source="openfda", topic=topic, output_dir=chunks_dir):
            if chunk.chunk_id not in seen_ids:
                seen_ids.add(chunk.chunk_id)
                chunks.append(chunk)
    return chunks


def main():
    driver = get_neo4j_driver(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    setup_constraints(driver)

    logger.info("Loading OpenFDA chunks...")
    chunks = load_all_openfda_chunks(CHUNKS_DIR)
    logger.info(f"  {len(chunks)} unique chunks loaded")

    logger.info("Extracting relationships...")
    all_relationships = []
    for i, chunk in enumerate(chunks):
        all_relationships.extend(extract_relationships_from_chunk(chunk))
        if (i + 1) % 1000 == 0:
            logger.info(f"  processed {i + 1}/{len(chunks)} chunks...")
    logger.info(f"  {len(all_relationships)} raw relationships extracted")

    final_relationships = aggregate_relationships(all_relationships)
    logger.info(f"  {len(final_relationships)} unique relationships after aggregation")

    logger.info("Writing to Neo4j...")
    write_relationships_batched(driver, final_relationships)

    with driver.session() as session:
        drug_count = session.run("MATCH (d:Drug) RETURN count(d) AS count").single()["count"]
        disease_count = session.run("MATCH (dis:Disease) RETURN count(dis) AS count").single()["count"]
        rel_count = session.run("MATCH ()-[r]->() RETURN count(r) AS count").single()["count"]

    logger.info(f"Verified Drug nodes: {drug_count}")
    logger.info(f"Verified Disease nodes: {disease_count}")
    logger.info(f"Verified relationships: {rel_count}")

    driver.close()


if __name__ == "__main__":
    main()