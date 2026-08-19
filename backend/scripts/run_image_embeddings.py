"""
Generate CLIP embeddings for all unique WHO images.

Run from the backend/ folder:
    cd backend
    python scripts/run_image_embeddings.py

Deduplicates images across topic files (same content-hash approach used
for chunks in Phase 6/run_chunking.py), with cover-page-position images
excluded from cross-topic merging - see image_embedder.py's module
docstring for why.
"""

import sys
import os
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from medrag.ingestion.storage import load_who_images
from medrag.embeddings.image_embedder import embed_who_images
from medrag.embeddings.storage import save_image_embeddings

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("medrag.embeddings")

IMAGE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "images", "who"))
EMBEDDING_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "processed", "embeddings"))

WHO_TOPICS = [
    "tuberculosis", "hypertension", "diabetes", "obesity", "asthma", "copd",
    "coronary artery disease", "heart failure", "stroke", "hyperlipidemia",
    "pneumonia", "covid-19", "malaria", "hiv aids", "hepatitis b", "hepatitis c",
    "dengue fever", "typhoid", "depression", "anxiety disorder", "epilepsy",
    "malnutrition", "anemia in pregnancy", "breast cancer",
]


def main():
    records, embeddings, topics_per_record = embed_who_images(WHO_TOPICS, load_who_images, IMAGE_DIR)
    npy_path, index_path = save_image_embeddings(records, embeddings, topics_per_record, output_dir=EMBEDDING_DIR)

    logger.info(f"=== DONE === {len(records)} unique image embeddings saved -> {npy_path.name}")


if __name__ == "__main__":
    main()