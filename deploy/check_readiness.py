"""Read-only public-demo gate. Never generates answers or provisions data."""
import os


def validate_environment(env):
    failures = []
    if env.get("AUTH_REQUIRED", "").lower() != "true":
        failures.append("Authentication must be enabled")
    if env.get("AUTH_COOKIE_SECURE", "").lower() != "true":
        failures.append("HTTPS cookies must be enabled")
    for name in ("POSTGRES_PASSWORD", "NEO4J_PASSWORD"):
        value = env.get(name, "")
        if len(value) < 20 or value.lower() in {"medragpassword", "ci-test-password"}:
            failures.append(f"{name} must be a unique password of at least 20 characters")
    if not env.get("OPENAI_API_KEY"):
        failures.append("An OpenAI API key is required")
    return failures


def check_corpus(client, driver):
    from qdrant_client import models
    from medrag.embeddings.qdrant_client import TEXT_COLLECTION, DENSE_VECTOR_NAME, SPARSE_VECTOR_NAME, TEXT_VECTOR_SIZE
    from medrag.retrieval.hybrid_search import build_user_filter
    failures = []
    info = client.get_collection(TEXT_COLLECTION)
    vectors = info.config.params.vectors
    sparse = info.config.params.sparse_vectors or {}
    if not isinstance(vectors, dict) or DENSE_VECTOR_NAME not in vectors or vectors[DENSE_VECTOR_NAME].size != TEXT_VECTOR_SIZE:
        failures.append("Text collection must have the expected 1536-dimensional dense vector")
    if SPARSE_VECTOR_NAME not in sparse:
        failures.append("Text collection must have the sparse retrieval vector")
    counts = {}
    for source in ("pubmed", "openfda", "who"):
        scope = models.Filter(must=[build_user_filter(None), models.FieldCondition(key="source", match=models.MatchValue(value=source))])
        counts[source] = client.count(TEXT_COLLECTION, count_filter=scope, exact=True).count
        if counts[source] == 0:
            failures.append(f"No visible curated {source} chunks; provision the corpus first")
    with driver.session() as session:
        record = session.run("MATCH ()-[r:TREATS|CONTRAINDICATED_IN|CAUSES]->() RETURN count(r) AS relationships").single()
        relationships = record["relationships"] if record else 0
        if not relationships:
            failures.append("No expected medical graph relationships; provision the graph first")
    return failures, counts, relationships


def main():
    failures = validate_environment(os.environ)
    if failures:
        raise SystemExit("Deployment configuration failed: " + "; ".join(failures))
    from config.settings import settings
    from neo4j import GraphDatabase
    from medrag.embeddings.qdrant_client import get_qdrant_client
    client = get_qdrant_client(settings.qdrant_url)
    driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
    try:
        failures, counts, relationships = check_corpus(client, driver)
        print("Visible curated source counts:", counts, "medical graph relationships:", relationships)
        if failures:
            raise SystemExit("Corpus readiness failed: " + "; ".join(failures))
        print("Configuration and corpus checks passed. Browser HTTPS and answer-quality checks remain separate.")
    finally:
        client.close()
        driver.close()


if __name__ == "__main__":
    main()
