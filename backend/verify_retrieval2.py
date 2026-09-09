from config.settings import settings
from medrag.embeddings.qdrant_client import get_qdrant_client
from medrag.retrieval.hybrid_search import hybrid_search

client = get_qdrant_client(settings.qdrant_url or "http://localhost:6333")
results = hybrid_search(client, "metformin dosage for diabetes", limit=5, per_signal_limit=5)
for r in results:
    print(f"{r['fused_score']:.5f}  {r['payload']['source']}  {r['chunk_id']}")
