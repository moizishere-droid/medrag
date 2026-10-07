"""Source visuals preserve original cells and never cross the curated boundary."""
import json
import hashlib
from pathlib import Path

from medrag.citations.visuals import VisualCatalog, attach_source_visuals, table_text


def catalog_at(root):
    images = root / "images" / "who"
    tables = root / "tables" / "who"
    images.mkdir(parents=True)
    tables.mkdir(parents=True)
    (images / "figure.png").write_bytes(b"png fixture")
    (images / "unlisted.png").write_bytes(b"not in manifest")
    (images / "diabetes_metadata.jsonl").write_text(json.dumps({
        "filename": "figure.png", "topic": "diabetes", "page_number": 4,
        "image_type": "rasterized_page"}) + "\n")
    (images / "verified_figures.jsonl").write_text(json.dumps({
        "filename": "figure.png", "source_id": "diabetes", "figure_number": "1",
        "page_number": 4, "caption": "Fig. 1. Example source evidence", "image_type": "rasterized_page",
        "sha256": hashlib.sha256(b"png fixture").hexdigest()}) + "\n")
    rows = [["Drug\nname", "Dose | note"], ["A (Figure 1)", None]]
    (tables / "diabetes.jsonl").write_text(json.dumps({
        "topic": "diabetes", "page_number": 2, "table_data": rows}) + "\n")
    return VisualCatalog(root), rows


def result(rows, source="who", source_id="diabetes", chunk_id="table1"):
    return {"payload": {"source": source, "source_id": source_id, "chunk_id": chunk_id,
                        "chunk_type": "table", "raw_text": table_text(rows),
                        "metadata": {"page_number": 2},
                        "linked_images": [{"filename": "figure.png", "figure_number": 1}]}}


def citations(*results):
    return [{"marker": i + 1, "chunk_id": r["payload"]["chunk_id"], "title": "Source"}
            for i, r in enumerate(results)]


def test_existing_index_resolves_exact_original_cells_and_image_provenance(tmp_path):
    catalog, rows = catalog_at(tmp_path)
    hit = result(rows)
    output = attach_source_visuals(citations(hit), [hit], catalog)
    assert output[0]["table"]["rows"] == [["Drug\nname", "Dose | note"], ["A (Figure 1)", ""]]
    assert output[0]["table"]["page_number"] == 2
    assert output[0]["images"] == [{"filename": "figure.png", "page_number": 4,
                                     "figure_number": "1", "image_type": "rasterized_page",
                                     "caption": "Fig. 1. Example source evidence"}]


def test_private_uploads_cannot_resolve_curated_media(tmp_path):
    catalog, rows = catalog_at(tmp_path)
    hit = result(rows, source="user_upload")
    output = attach_source_visuals(citations(hit), [hit], catalog)
    assert output[0]["table"] is None and output[0]["images"] == []


def test_unrelated_source_missing_files_and_uncited_hits_are_excluded(tmp_path):
    catalog, rows = catalog_at(tmp_path)
    hit = result(rows, source_id="hypertension")
    assert attach_source_visuals(citations(hit), [hit], catalog)[0]["images"] == []
    assert attach_source_visuals([], [result(rows)], catalog) == []
    (catalog.image_root / "figure.png").unlink()
    assert attach_source_visuals(citations(result(rows)), [result(rows)], catalog)[0]["images"] == []


def test_deduplicates_figures_and_only_keeps_matched_table_cells(tmp_path):
    catalog, rows = catalog_at(tmp_path)
    hit = result(rows)
    other = result(rows, chunk_id="table2")
    other["payload"]["raw_text"] = "not a saved source table"
    output = attach_source_visuals(citations(hit, other), [hit, other], catalog)
    assert output[0]["images"] and not output[1]["images"]
    assert output[1]["table"] is None


def test_manifest_only_media_and_path_escape_rejected(tmp_path):
    catalog, _ = catalog_at(tmp_path)
    assert catalog.image_path("figure.png")
    for name in ["../figure.png", "..\\figure.png", "C:figure.png", "unlisted.png", "file.json", ""]:
        assert catalog.image_path(name) is None
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"outside")
    # Resolving a symlink outside the curated directory must also fail.
    try:
        (catalog.image_root / "escape.png").symlink_to(outside)
    except OSError:
        return  # Windows can disallow creating symlinks for unprivileged users.
    catalog.images["escape.png"] = {"topic": "diabetes"}
    assert catalog.image_path("escape.png") is None


def test_new_table_metadata_works_without_saved_table_files(tmp_path):
    catalog = VisualCatalog(tmp_path)
    rows = [["Header", "Value"], ["A", "2"]]
    hit = result(rows)
    hit["payload"]["metadata"]["table_data"] = rows
    output = attach_source_visuals(citations(hit), [hit], catalog)
    assert output[0]["table"]["rows"] == rows


def test_token_fragments_never_reconstruct_a_full_uncited_table(tmp_path):
    catalog = VisualCatalog(tmp_path)
    rows = [["A", "2"]]
    hit = result(rows)
    hit["payload"]["raw_text"] = "A"
    hit["payload"]["metadata"]["table_data"] = rows
    assert attach_source_visuals(citations(hit), [hit], catalog)[0]["table"] is None
