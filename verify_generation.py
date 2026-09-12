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

import openai
from neo4j import GraphDatabase
from config.settings import settings
from medrag.embeddings.qdrant_client import get_qdrant_client
from medrag.generation.generation import generate_answer

qdrant = get_qdrant_client(settings.qdrant_url or "http://localhost:6333")
neo4j_driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
openai_client = openai.OpenAI(api_key=settings.openai_api_key)

answer = generate_answer(
    "What does metformin treat and what are its contraindications?",
    qdrant_client=qdrant,
    openai_client=openai_client,
    neo4j_driver=neo4j_driver,
)
print(answer)
