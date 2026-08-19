"""
Storage for generated embeddings: a compact numpy array per source, plus a
JSONL index mapping each array row back to its chunk's identity/metadata.

Splitting storage this way (rather than storing the vector inside each
chunk's JSON) keeps embeddings in an efficient binary format while the
index stays human-readable and directly usable for Phase 9's Qdrant upload
(point_id + vector + payload).
"""

import json
from pathlib import Path
from typing import List, Tuple

import numpy as np

from medrag.processing.models import Chunk


def save_embeddings(chunks: List[Chunk], embeddings: np.ndarray, source: str, output_dir: str) -> Tuple[Path, Path]:
    """
    Save embeddings as a .npy array and a parallel .jsonl index (same row
    order) to output_dir/{source}_embeddings.npy and {source}_index.jsonl.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    npy_path = Path(output_dir) / f"{source}_embeddings.npy"
    np.save(npy_path, embeddings)

    index_path = Path(output_dir) / f"{source}_index.jsonl"
    with open(index_path, "w", encoding="utf-8") as f:
        for chunk in chunks:
            record = {
                "point_id": chunk.point_id,
                "chunk_id": chunk.chunk_id,
                "source": chunk.source,
                "topics": chunk.topics,
                "source_id": chunk.source_id,
                "chunk_type": chunk.chunk_type,
            }
            f.write(json.dumps(record) + "\n")

    return npy_path, index_path


def load_embeddings(source: str, output_dir: str) -> Tuple[np.ndarray, List[dict]]:
    """Load a source's embeddings array and its index back."""
    npy_path = Path(output_dir) / f"{source}_embeddings.npy"
    index_path = Path(output_dir) / f"{source}_index.jsonl"

    embeddings = np.load(npy_path)

    index = []
    with open(index_path, "r", encoding="utf-8") as f:
        for line in f:
            index.append(json.loads(line))

    return embeddings, index


def save_image_embeddings(records, embeddings: np.ndarray, topics_per_record, output_dir: str) -> Tuple[Path, Path]:
    """
    Save WHO image embeddings as a .npy array and a parallel .jsonl index
    (same row order) to output_dir/who_images_embeddings.npy and
    who_images_index.jsonl.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    npy_path = Path(output_dir) / "who_images_embeddings.npy"
    np.save(npy_path, embeddings)

    index_path = Path(output_dir) / "who_images_index.jsonl"
    with open(index_path, "w", encoding="utf-8") as f:
        for record, topics in zip(records, topics_per_record):
            entry = {
                "filename": record.filename,
                "topics": topics,
                "page_number": record.page_number,
                "image_type": record.image_type,
            }
            f.write(json.dumps(entry) + "\n")

    return npy_path, index_path


def load_image_embeddings(output_dir: str) -> Tuple[np.ndarray, List[dict]]:
    """Load WHO image embeddings and their index back."""
    npy_path = Path(output_dir) / "who_images_embeddings.npy"
    index_path = Path(output_dir) / "who_images_index.jsonl"

    embeddings = np.load(npy_path)

    index = []
    with open(index_path, "r", encoding="utf-8") as f:
        for line in f:
            index.append(json.loads(line))

    return embeddings, index