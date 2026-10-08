"""Initialize only the isolated local Docker corpus; preserve existing records."""
import os
import subprocess
import sys
import time
from pathlib import Path


def main():
    if os.environ.get("MEDRAG_LOCAL_BOOTSTRAP") != "true":
        raise RuntimeError("This helper is restricted to the local Docker stack")
    if os.environ.get("QDRANT_URL") != "http://qdrant:6333" or os.environ.get("NEO4J_URI") != "bolt://neo4j:7687":
        raise RuntimeError("Unexpected local service addresses")
    for name in ("POSTGRES_PASSWORD", "NEO4J_PASSWORD"):
        if not os.environ.get(name):
            raise RuntimeError(name + " must not be empty")
    from config.settings import settings
    from neo4j import GraphDatabase
    from medrag.embeddings.qdrant_client import get_qdrant_client, TEXT_COLLECTION
    from check_readiness import check_corpus
    client = get_qdrant_client(settings.qdrant_url)
    driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
    try:
        deadline = time.monotonic() + 180
        while True:
            try:
                client.get_collections()
                driver.verify_connectivity()
                break
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(3)
        if client.collection_exists(TEXT_COLLECTION):
            failures, counts, relationships = check_corpus(client, driver)
            if not failures:
                print("Existing corpus ready:", counts, "graph relationships:", relationships, flush=True)
                return
        processed = Path("/app/data/processed")
        for source in ("pubmed", "openfda", "who"):
            if not list((processed / "chunks" / source).glob("*.jsonl")):
                raise RuntimeError("Missing prepared chunks for " + source)
            for suffix in ("_embeddings.npy", "_index.jsonl"):
                if not (processed / "embeddings" / (source + suffix)).is_file():
                    raise RuntimeError("Missing saved embedding artifact for " + source)
        for script in ("run_qdrant_ingestion.py", "run_graph_ingestion.py"):
            subprocess.run([sys.executable, "backend/scripts/" + script], check=True)
        failures, counts, relationships = check_corpus(client, driver)
        if failures:
            raise RuntimeError("Corpus initialization failed: " + "; ".join(failures))
        print("Local corpus ready:", counts, "graph relationships:", relationships, flush=True)
    finally:
        client.close()
        driver.close()


if __name__ == "__main__":
    main()
