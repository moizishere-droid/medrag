"""Real local vector storage round trips with only encoders mocked."""
from types import SimpleNamespace
from contextlib import closing
from unittest.mock import Mock

import numpy as np
import pytest
from qdrant_client import QdrantClient

from medrag.embeddings import qdrant_client as schema, qdrant_ingestion as ingestion, storage, image_embedder
from medrag.processing import image_linking
from medrag.processing.models import Chunk
from medrag.ingestion.models import WhoImage


@pytest.fixture
def chunk():
    cid = "curated_test"
    return Chunk(chunk_id=cid, point_id=Chunk.make_point_id(cid), text="Evidence", raw_text="Evidence", source="who", topics=["diabetes"], source_id="diabetes", chunk_index=0)


def test_curated_vector_ingestion_is_idempotent_and_preserves_links(monkeypatch, chunk):
    sparse = SimpleNamespace(indices=np.array([1, 2]), values=np.array([1.0, 2.0]))
    monkeypatch.setattr(ingestion, "get_sparse_model", lambda: SimpleNamespace(embed=lambda texts: [sparse for _ in texts]))
    vector = np.zeros((1, schema.TEXT_VECTOR_SIZE), dtype=np.float32)
    vector[0, 0] = 1
    links = [{"chunk_id": chunk.chunk_id, "point_id": chunk.point_id, "image_filename": "figure.png", "figure_number": 1}]
    to_images, to_chunks = ingestion.build_link_maps(ingestion.dedupe_links(links * 2))
    with closing(QdrantClient(location=":memory:")) as client:
        schema.ensure_collections(client)
        for _ in range(2):
            assert ingestion.upload_source_chunks(client, "who", {chunk.chunk_id: chunk}, vector, [{"chunk_id": chunk.chunk_id}], to_images) == 1
            schema.ensure_collections(client)
        assert client.count(schema.TEXT_COLLECTION, exact=True).count == 1
        point = client.retrieve(schema.TEXT_COLLECTION, [chunk.point_id])[0]
        assert point.payload["linked_images"][0]["point_id"] == schema.generate_image_point_id("figure.png")
        assert "user_id" not in point.payload
        assert ingestion.upload_images(client, [{"filename": "figure.png", "topics": ["diabetes"], "page_number": 0, "image_type": "embedded"}], np.ones((1, 512)), to_chunks) == 1
        assert client.count(schema.IMAGE_COLLECTION, exact=True).count == 1


def test_sparse_count_mismatch_never_writes(monkeypatch, chunk):
    monkeypatch.setattr(ingestion, "get_sparse_model", lambda: SimpleNamespace(embed=lambda texts: []))
    client = Mock()
    with pytest.raises(ValueError, match="Sparse response count"):
        ingestion.upload_source_chunks(client, "who", {chunk.chunk_id: chunk}, np.zeros((1, 1536)), [{"chunk_id": chunk.chunk_id}])
    client.upsert.assert_not_called()


def test_embedding_storage_round_trips_and_rejects_corrupted_index(tmp_path, chunk):
    vector = np.ones((1, 1536), dtype=np.float32)
    _, index = storage.save_embeddings([chunk], vector, "who", str(tmp_path))
    loaded, rows = storage.load_embeddings("who", str(tmp_path))
    assert np.array_equal(loaded, vector) and rows[0]["point_id"] == chunk.point_id
    index.write_text("", encoding="utf-8")
    with pytest.raises(ValueError, match="matching rows"):
        storage.load_embeddings("who", str(tmp_path))


def test_empty_image_pipeline_produces_saveable_vectors(tmp_path):
    records, vectors, topics = image_embedder.embed_who_images([], lambda *a, **k: [], str(tmp_path))
    assert vectors.shape == (0, 512)
    storage.save_image_embeddings(records, vectors, topics, str(tmp_path))
    loaded, rows = storage.load_image_embeddings(str(tmp_path))
    assert loaded.shape == (0, 512) and rows == []


def test_image_links_require_aligned_topics_and_verified_captions(chunk):
    image = WhoImage(topic="diabetes", page_number=0, image_index=0, filename="diabetes_page0_img0.png", width=100, height=100)
    with pytest.raises(ValueError, match="matching lengths"):
        image_linking.group_images_by_document([image], [])
    chunk.raw_text = "See Figure 1 for the evidence."
    links, stats = image_linking.link_images_to_chunks([chunk], [image], [["diabetes"]])
    assert links == []  # Extraction order is not figure identity.
    links, stats = image_linking.link_images_to_chunks([chunk], [image], [["diabetes"]],
        {("diabetes", "1"): {"filename": image.filename}})
    assert links[0]["image_filename"] == image.filename and stats["unique_images_linked"] == 1
    chunk.raw_text = "Figure 1; Figure 2; Figure 3; contents."
    links, stats = image_linking.link_images_to_chunks([chunk], [image], [["diabetes"]])
    assert links == [] and stats["listing_chunks_skipped"] == 1
