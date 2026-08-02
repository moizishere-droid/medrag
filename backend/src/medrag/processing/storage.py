"""
Local storage for chunks - one JSONL file per topic per source.
"""

import json
from pathlib import Path
from typing import List

from medrag.processing.models import Chunk


def save_chunks(chunks: List[Chunk], source: str, topic: str, output_dir: str) -> Path:
    """Write chunks to data/processed/chunks/{source}/{topic}.jsonl."""
    source_dir = Path(output_dir) / source
    source_dir.mkdir(parents=True, exist_ok=True)
    filepath = source_dir / f"{topic.replace(' ', '_')}.jsonl"

    with open(filepath, "w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(chunk.model_dump_json() + "\n")

    return filepath


def load_chunks(source: str, topic: str, output_dir: str) -> List[Chunk]:
    """Load all saved chunks for a topic/source back into Chunk objects."""
    filepath = Path(output_dir) / source / f"{topic.replace(' ', '_')}.jsonl"
    chunks = []
    if not filepath.exists():
        return chunks

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            chunks.append(Chunk(**data))
    return chunks