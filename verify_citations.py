import sys, os
from pathlib import Path

def find_project_root(marker="backend", start=None):
    current = Path(start or os.getcwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / marker).is_dir():
            return candidate
    raise RuntimeError(f"Could not find a {marker} folder above {current}")

PROJECT_ROOT = find_project_root()
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
sys.path.insert(0, str(PROJECT_ROOT / "backend" / "src"))

from config.settings import settings
from medrag.embeddings.qdrant_client import get_qdrant_client
from medrag.retrieval.reranking import search_with_reranking
from medrag.citations.citations import build_who_source_url_lookup, build_citations

WHO_RAW_DIR = str(PROJECT_ROOT / "data" / "raw" / "who")
who_source_urls = build_who_source_url_lookup(WHO_RAW_DIR)

qdrant = get_qdrant_client(settings.qdrant_url or "http://localhost:6333")
results = search_with_reranking(qdrant, "side effects of ACE inhibitors", candidate_pool_size=20, top_n=5)

answer_text = "The major adverse effects of ACE inhibitors include dry cough and renal dysfunction in patients with impaired renal function [1]. Additionally, ACE inhibitors have been associated with angioedema, hypovolemia, hypotension, hyperkalemia, and, more rarely, cholestatic jaundice, hepatic failure, neutropenia, and agranulocytosis [3]."

citations = build_citations(answer_text, results, who_source_urls)
for c in citations:
    print(c)
