"""Explicit opt-in live before/after benchmark; writes only to medrag_chat_test."""
import argparse
import importlib
import json
import logging
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Allow six paid embedding/answer requests")
    args = parser.parse_args()
    if not args.live:
        parser.error("This benchmark calls paid APIs. Pass --live to opt in.")
    import openai
    import psycopg2
    from neo4j import GraphDatabase
    from config.settings import settings
    from medrag.embeddings.qdrant_client import get_qdrant_client
    from medrag.memory import chat_memory as cm
    from medrag.retrieval.onnx_reranker import OnnxReranker
    rr = importlib.import_module("medrag.retrieval.reranking")
    rows, sessions = [], []
    conn = psycopg2.connect(host=settings.postgres_host, port=settings.postgres_port,
                           dbname="medrag_chat_test", user=settings.postgres_user, password=settings.postgres_password)
    assert conn.get_dsn_parameters()["dbname"] == "medrag_chat_test"
    conn.autocommit = True
    qdrant = get_qdrant_client(settings.qdrant_url)
    client = openai.OpenAI(api_key=settings.openai_api_key)
    driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
    class Timings(logging.Handler):
        latest = ""
        def emit(self, record):
            if record.getMessage().startswith("Chat pipeline seconds"):
                self.latest = record.getMessage()
    handler = Timings()
    logger = logging.getLogger("medrag.memory")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        settings.rerank_backend = "torch"
        rr._cross_encoder_cache = None
        rr.warmup_retrieval()
        original = rr.get_cross_encoder()
        optimized = OnnxReranker(original, ROOT / ".medrag_cache", settings.rerank_threads)
        cm.get_all_known_drug_names(driver)  # exclude first-load graph setup in both modes
        for mode, encoder in [("torch", original), ("onnx", optimized)]:
            rr._cross_encoder_cache = encoder
            for query in ["What is type 2 diabetes?", "What is hypertension?", "What is metformin used for?"]:
                sid = cm.create_session(conn, title="Latency benchmark")
                sessions.append(sid)
                started = perf_counter()
                answer, results, _ = cm.generate_answer_with_memory(query, sid, conn, qdrant, client,
                                                                    neo4j_driver=driver, user_id=sid)
                row = {"backend": mode, "query": query, "seconds": round(perf_counter() - started, 3),
                       "stages": handler.latest, "top_chunks": [r["payload"]["chunk_id"] for r in results],
                       "answer_characters": len(answer)}
                rows.append(row)
                print(json.dumps(row), flush=True)
        for before, after in zip(rows[:3], rows[3:]):
            if before["top_chunks"] != after["top_chunks"]:
                raise RuntimeError("Retrieved top-five evidence differs; do not accept this benchmark.")
        (ROOT / "docs" / "performance_benchmark.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    finally:
        logger.removeHandler(handler)
        with conn.cursor() as cur:
            for sid in sessions:
                cur.execute("DELETE FROM sessions WHERE session_id = %s", (sid,))
        conn.close()
        driver.close()
        client.close()
        qdrant.close()


if __name__ == "__main__":
    main()
