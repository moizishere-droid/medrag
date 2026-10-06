"""Round-trip saved source artifacts through their maintained readers."""
from io import BytesIO

from PIL import Image

from medrag.ingestion import storage
from medrag.ingestion.models import DrugRecord, Guideline
from medrag.processing import storage as chunk_storage
from medrag.processing.models import Chunk


def test_source_storage_round_trips_shared_topic_and_image_metadata(tmp_path):
    topic = "heart failure"
    drug = DrugRecord(brand_name="Test", generic_name="Test", indications_and_usage="Evidence", topic=topic)
    storage.save_drugs([drug], topic, str(tmp_path))
    assert storage.load_drugs(topic, str(tmp_path)) == [drug]
    storage.save_drugs([], topic, str(tmp_path))
    assert storage.load_drugs(topic, str(tmp_path)) == []
    guideline = Guideline(title="Guide", topic=topic, clean_text="Evidence", raw_text="Evidence", num_pages=1, num_tables=1, num_images=1, source_url="https://example.org/doc.pdf")
    storage.save_guideline(guideline, str(tmp_path))
    assert storage.load_guideline(topic, str(tmp_path)) == guideline
    storage.save_who_tables([{"page_number": 0, "table_data": [["Dose", None], ["10", "mg"]]}], topic, str(tmp_path))
    table = storage.load_who_tables(topic, str(tmp_path))[0]
    assert table.page_number == 0 and table.table_data[0][1] is None
    with Image.new("RGB", (100, 120), "white") as image:
        buffer = BytesIO()
        image.save(buffer, format="PNG")
    records = storage.save_who_images([{"image_bytes": buffer.getvalue(), "page_number": 0, "width": 100, "height": 120, "image_type": "rasterized_page"}], topic, str(tmp_path))
    assert storage.load_who_images(topic, str(tmp_path)) == records
    with Image.open(tmp_path / records[0].filename) as saved:
        assert saved.size == (100, 120)


def test_missing_sources_are_distinct_from_corrupt_sources(tmp_path):
    assert storage.load_drugs("absent", str(tmp_path)) == []
    assert storage.load_guideline("absent", str(tmp_path)) is None
    assert storage.load_who_tables("absent", str(tmp_path)) == []
    assert storage.load_who_images("absent", str(tmp_path)) == []
    assert storage.load_articles("absent", str(tmp_path)) == []


def test_chunk_storage_round_trips_with_normalized_topic_filename(tmp_path):
    topic = "heart failure"
    assert chunk_storage.load_chunks("who", topic, str(tmp_path)) == []
    cid = "heart_failure_who_0"
    chunk = Chunk(chunk_id=cid, point_id=Chunk.make_point_id(cid), text="Guide: evidence", raw_text="evidence", source="who", topics=[topic], source_id=topic, chunk_index=0)
    chunk_storage.save_chunks([chunk], "who", topic, str(tmp_path))
    assert chunk_storage.load_chunks("who", topic, str(tmp_path)) == [chunk]
