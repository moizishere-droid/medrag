"""Wait for disposable CI services and seed synthetic graph contract data.

Never run ingestion or connect this helper to a production graph.
"""
import os
import time
from urllib.parse import urlparse

import psycopg2
import requests
from neo4j import GraphDatabase


def main():
    targets = {
        "QDRANT_URL": "vector-ci",
        "NEO4J_URI": "graph-ci",
        "POSTGRES_HOST": "postgres-ci",
    }
    if os.environ.get("MEDRAG_CI") != "true":
        raise RuntimeError("CI seed is restricted to disposable CI services")
    for key, hostname in targets.items():
        value = os.environ[key]
        actual = value if key == "POSTGRES_HOST" else urlparse(value).hostname
        if actual != hostname:
            raise RuntimeError(f"Refusing non-CI service in {key}")

    deadline = time.monotonic() + 180
    while True:
        try:
            response = requests.get(os.environ["QDRANT_URL"] + "/collections", timeout=5)
            response.raise_for_status()
            with psycopg2.connect(
                host="postgres-ci", port=5432, dbname="medrag_chat",
                user=os.environ["POSTGRES_USER"], password=os.environ["POSTGRES_PASSWORD"],
                connect_timeout=5,
            ) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
            with GraphDatabase.driver(
                os.environ["NEO4J_URI"],
                auth=(os.environ["NEO4J_USER"], os.environ["NEO4J_PASSWORD"]),
                connection_timeout=5,
            ) as driver:
                driver.verify_connectivity()
                with driver.session() as session:
                    session.run("""
                        MERGE (d:Drug {normalized_name: 'ci synthetic drug'})
                        SET d.name = 'CI Synthetic Drug'
                        MERGE (a:Disease {name: 'CI Synthetic Indication'})
                        MERGE (b:Disease {name: 'CI Synthetic Contraindication'})
                        MERGE (c:Disease {name: 'CI Synthetic Adverse Effect'})
                        MERGE (d)-[:TREATS]->(a)
                        MERGE (d)-[:CONTRAINDICATED_IN]->(b)
                        MERGE (d)-[:CAUSES]->(c)
                    """).consume()
            print("Disposable services ready; synthetic graph fixture seeded.")
            return
        except (requests.RequestException, psycopg2.Error, OSError) as exc:
            if time.monotonic() >= deadline:
                raise RuntimeError("CI services did not become ready") from exc
            time.sleep(3)
        except Exception as exc:
            # Neo4j connectivity/auth errors use the driver's own exception types.
            from neo4j.exceptions import Neo4jError, ServiceUnavailable, SessionExpired
            if not isinstance(exc, (Neo4jError, ServiceUnavailable, SessionExpired)):
                raise
            if time.monotonic() >= deadline:
                raise RuntimeError("CI graph did not become ready") from exc
            time.sleep(3)


if __name__ == "__main__":
    main()
