"""
Local JSONL storage for ingested articles — one file per topic.
"""

import json
from pathlib import Path
from typing import List, Set, Optional

from medrag.ingestion.models import Article, DrugRecord, Guideline, WhoTable, WhoImage


def save_articles(articles: List[Article], topic: str, output_dir: str) -> Path:
    """Append articles to data/raw/pubmed/{topic}.jsonl (one JSON object per line)."""
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filepath = Path(output_dir) / f"{topic}.jsonl"

    with open(filepath, "a", encoding="utf-8") as f:
        for article in articles:
            f.write(article.model_dump_json() + "\n")

    return filepath


def load_articles(topic: str, output_dir: str) -> List[Article]:
    """Load all saved articles for a topic back into Article objects."""
    filepath = Path(output_dir) / f"{topic}.jsonl"
    articles = []
    if not filepath.exists():
        return articles

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            articles.append(Article(**data))
    return articles


def get_existing_pmids(topic: str, output_dir: str) -> Set[str]:
    """Return the set of PMIDs already saved for a topic, for idempotent re-runs."""
    filepath = Path(output_dir) / f"{topic}.jsonl"
    if not filepath.exists():
        return set()

    existing = set()
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            existing.add(data["pmid"])
    return existing


def load_drugs(topic: str, output_dir: str) -> List[DrugRecord]:
    """Load all saved drug records for a topic back into DrugRecord objects."""
    filepath = Path(output_dir) / f"{topic}.jsonl"
    drugs = []
    if not filepath.exists():
        return drugs

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            drugs.append(DrugRecord(**data))
    return drugs


def save_drugs(drugs: List[DrugRecord], topic: str, output_dir: str) -> Path:
    """
    Write drug records for a topic to data/raw/openfda/{topic}.jsonl.

    Unlike save_articles (append), this OVERWRITES the file each run —
    OpenFDA drug labels aren't a growing corpus like papers; each run
    fetches the current best matches fresh, so overwrite avoids
    accumulating duplicates across repeated runs.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filepath = Path(output_dir) / f"{topic}.jsonl"

    with open(filepath, "w", encoding="utf-8") as f:
        for drug in drugs:
            f.write(drug.model_dump_json() + "\n")

    return filepath


def save_guideline(guideline: Guideline, output_dir: str) -> Path:
    """
    Write a WHO guideline's full text to data/raw/who/{topic}.json.
    One file per topic (each topic maps to exactly one guideline document,
    though several topics may share the same underlying source document).
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filepath = Path(output_dir) / f"{guideline.topic.replace(' ', '_')}.json"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(guideline.model_dump_json())

    return filepath


def load_guideline(topic: str, output_dir: str) -> Optional[Guideline]:
    """Load a saved WHO guideline for a topic, or None if it doesn't exist
    (expected for the 12 topics with no dedicated WHO guideline)."""
    filepath = Path(output_dir) / f"{topic.replace(' ', '_')}.json"
    if not filepath.exists():
        return None

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return Guideline(**data)


def save_who_tables(tables: List[dict], topic: str, output_dir: str) -> Path:
    """
    Write tables extracted from a WHO guideline to data/tables/who/{topic}.jsonl.
    tables: list of {page_number, table_data} dicts from extract_full_document.
    """
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    filepath = Path(output_dir) / f"{topic.replace(' ', '_')}.jsonl"

    with open(filepath, "w", encoding="utf-8") as f:
        for t in tables:
            record = WhoTable(topic=topic, page_number=t["page_number"], table_data=t["table_data"])
            f.write(record.model_dump_json() + "\n")

    return filepath


def load_who_tables(topic: str, output_dir: str) -> List[WhoTable]:
    """Load all saved tables for a topic back into WhoTable objects."""
    filepath = Path(output_dir) / f"{topic.replace(' ', '_')}.jsonl"
    tables = []
    if not filepath.exists():
        return tables

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            tables.append(WhoTable(**data))
    return tables


def save_who_images(images: List[dict], topic: str, output_dir: str) -> List[WhoImage]:
    """
    Save extracted images as PNG files to data/images/who/, plus a metadata
    JSONL file. images: list of dicts from extract_images (with raw image_bytes).
    Returns the saved WhoImage records.
    """
    from PIL import Image
    import io as _io

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    saved_records = []

    for i, img in enumerate(images):
        pil_image = Image.open(_io.BytesIO(img["image_bytes"]))
        filename = f"{topic.replace(' ', '_')}_page{img['page_number']}_img{i}.png"
        filepath = Path(output_dir) / filename
        pil_image.save(filepath, "PNG")

        record = WhoImage(
            topic=topic,
            page_number=img["page_number"],
            image_index=i,
            filename=filename,
            width=img["width"],
            height=img["height"],
        )
        saved_records.append(record)

    meta_path = Path(output_dir) / f"{topic.replace(' ', '_')}_metadata.jsonl"
    with open(meta_path, "w", encoding="utf-8") as f:
        for record in saved_records:
            f.write(record.model_dump_json() + "\n")

    return saved_records


def load_who_images(topic: str, output_dir: str) -> List[WhoImage]:
    """Load saved image metadata for a topic back into WhoImage objects."""
    meta_path = Path(output_dir) / f"{topic.replace(' ', '_')}_metadata.jsonl"
    images = []
    if not meta_path.exists():
        return images

    with open(meta_path, "r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line)
            images.append(WhoImage(**data))
    return images