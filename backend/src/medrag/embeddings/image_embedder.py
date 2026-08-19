"""
Image embedding generation via CLIP (ViT-B-32, openai pretrained weights)
for WHO images. Runs locally, no API cost.

WHO images are saved per-topic (like WHO chunks were), so the same image
can legitimately be saved under multiple topic files when its source
document is shared across topics (asthma/copd, the CVD risk group, mhGAP).
Images are deduplicated by content hash before embedding, with one
exception: cover-page-position images (filename matching *_page0_img0.png)
are NEVER merged across topics even if their content hash matches, since
that reflects two unrelated documents coincidentally using the same WHO
PDF cover template - not real shared content. Confirmed as a real case in
this project's data (pneumonia and malnutrition, unrelated documents,
sharing an identical cover graphic).

CLIP's known limitation for this project: it resizes every image to
224x224 before embedding, which is enough to capture general visual
layout/style but not to read dense paragraph text on rasterized document
pages. Same-document images score meaningfully higher in similarity than
cross-document ones (validated: ~0.73 vs ~0.55 in this project's data),
but the gap is real, not dramatic - WHO document pages share a broadly
similar visual style regardless of actual content.
"""

import re
import json
import hashlib
import logging
from pathlib import Path
from typing import List, Dict, Tuple
from collections import defaultdict

import numpy as np
import torch
import open_clip
from PIL import Image

from medrag.ingestion.models import WhoImage

logger = logging.getLogger("medrag.embeddings")

COVER_PAGE_PATTERN = re.compile(r"_page0_img0\.png$")

_model = None
_preprocess = None


def get_clip_model():
    """Load (once) and return the CLIP model and preprocessing pipeline."""
    global _model, _preprocess
    if _model is not None:
        return _model, _preprocess

    model, _, preprocess = open_clip.create_model_and_transforms('ViT-B-32', pretrained='openai')
    model.eval()
    _model, _preprocess = model, preprocess
    return _model, _preprocess


def compute_file_hash(filepath: Path) -> str:
    with open(filepath, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def deduplicate_images(topics: List[str], load_images_fn, image_dir: str) -> Tuple[Dict[str, WhoImage], Dict[str, List[str]]]:
    """
    Load images across all topics, deduplicate by content hash - except
    cover-page-position images, which are kept separate per topic even if
    their hash matches another document's cover graphic.

    Returns (key_to_image_record, key_to_topics).
    """
    key_to_topics = defaultdict(list)
    key_to_image = {}

    for topic in topics:
        images = load_images_fn(topic, output_dir=image_dir)
        for img in images:
            filepath = Path(image_dir) / img.filename
            if not filepath.exists():
                logger.warning(f"  Missing file: {img.filename} (referenced under topic '{topic}')")
                continue

            if COVER_PAGE_PATTERN.search(img.filename):
                key = f"{img.filename}_{topic}"
            else:
                key = compute_file_hash(filepath)

            key_to_topics[key].append(topic)
            if key not in key_to_image:
                key_to_image[key] = img

    return key_to_image, key_to_topics


def embed_image(filepath: Path) -> np.ndarray:
    """Embed a single image file with CLIP."""
    model, preprocess = get_clip_model()
    img = Image.open(filepath)
    img_tensor = preprocess(img).unsqueeze(0)
    with torch.no_grad():
        features = model.encode_image(img_tensor)
    return features[0].numpy()


def embed_who_images(topics: List[str], load_images_fn, image_dir: str) -> Tuple[List[WhoImage], np.ndarray, List[List[str]]]:
    """
    Full pipeline: deduplicate WHO images across all topics, then embed
    each unique image once with CLIP.
    Returns (unique_records, embeddings, topics_per_record) - all three
    lists/arrays are in matching order.
    """
    key_to_image, key_to_topics = deduplicate_images(topics, load_images_fn, image_dir)
    logger.info(f"  Deduplicated to {len(key_to_image)} unique images")

    records = []
    embeddings = []
    topics_per_record = []

    for key, record in key_to_image.items():
        filepath = Path(image_dir) / record.filename
        try:
            vec = embed_image(filepath)
            embeddings.append(vec)
            records.append(record)
            topics_per_record.append(key_to_topics[key])
        except Exception as e:
            logger.warning(f"  Failed to embed {record.filename}: {e}")

    return records, np.array(embeddings, dtype=np.float32), topics_per_record