import hashlib
import json
from pathlib import Path

from medrag.citations.visuals import VisualCatalog, attach_source_visuals, revalidate_saved_visuals
from medrag.processing.image_linking import extract_figure_references


def fixture_catalog(tmp_path):
    root = tmp_path / "images" / "who"
    root.mkdir(parents=True)
    (root / "diagram.png").write_bytes(b"labeled source page")
    (root / "tyres.png").write_bytes(b"wrong cover photo")
    records = [{"filename": "diagram.png", "source_id": "dengue fever", "figure_number": "2",
                "page_number": 16, "image_type": "rasterized_page",
                "caption": "Fig. 2. Dengue case classification by severity",
                "sha256": hashlib.sha256(b"labeled source page").hexdigest()}]
    (root / "verified_figures.jsonl").write_text(json.dumps(records[0]))
    return VisualCatalog(tmp_path)


def test_stale_ordinal_link_is_replaced_using_the_exact_caption(tmp_path):
    catalog = fixture_catalog(tmp_path)
    payload = {"source": "who", "source_id": "dengue fever", "chunk_id": "c",
               "raw_text": "Criteria for classification are in Figure 2.",
               "linked_images": [{"filename": "tyres.png", "figure_number": 2}]}
    citation = {"marker": 1, "chunk_id": "c", "source": "who", "source_id": "dengue fever",
                "images": [{"filename": "tyres.png", "figure_number": "2"}]}
    output = attach_source_visuals([citation], [{"payload": payload}], catalog)
    assert output[0]["images"][0]["filename"] == "diagram.png"
    assert revalidate_saved_visuals([citation], catalog)[0]["images"][0]["filename"] == "diagram.png"
    assert catalog.image_path("tyres.png") is None


def test_unverified_figures_and_changed_image_content_fail_closed(tmp_path):
    catalog = fixture_catalog(tmp_path)
    citation = {"source": "who", "source_id": "dengue fever", "images": [{"figure_number": "3"}]}
    assert revalidate_saved_visuals([citation], catalog)[0]["images"] == []
    (catalog.image_root / "diagram.png").write_bytes(b"changed content")
    updated = VisualCatalog(tmp_path)
    assert updated.image_path("diagram.png") is None


def test_decimal_figure_identifiers_are_not_truncated():
    assert extract_figure_references("Figure 3.2, Fig. 2a, Figure 7.") == ["3.2", "2a", "7"]


def test_real_dengue_mapping_never_uses_the_cover_photo():
    root = Path(__file__).resolve().parents[2] / "data"
    catalog = VisualCatalog(root)
    record = catalog.figures[("dengue fever", "2")]
    assert record["page_number"] == 16
    assert record["filename"] == "dengue_fever_page16_verified_fig2.png"
    assert "classification by severity" in record["caption"]
    assert catalog.image_path(record["filename"]) is not None
    assert catalog.image_path("dengue_fever_page0_img1.png") is None


def test_generation_knows_which_verified_figure_the_ui_can_attach(tmp_path):
    from medrag.generation.generation import format_context
    from medrag.citations.citations import build_citations

    catalog = fixture_catalog(tmp_path)
    results = [{"payload": {"source": "who", "source_id": "dengue fever", "chunk_id": "c",
                            "raw_text": "Classification criteria are presented in Figure 2."}}]
    context = format_context(results, visual_catalog=catalog)
    assert "Fig. 2. Dengue case classification by severity (PDF page 17)" in context
    citations = build_citations("The source figure is attached below [1].", results, {})
    assert attach_source_visuals(citations, results, catalog)[0]["images"][0]["filename"] == "diagram.png"
    results[0]["payload"]["source"] = "user_upload"
    assert "Verified source figures" not in format_context(results, visual_catalog=catalog)


def test_default_generation_catalog_finds_bundled_dengue_figure():
    from medrag.generation.generation import format_context

    results = [{"payload": {"source": "who", "source_id": "dengue fever", "chunk_id": "classification",
                            "raw_text": "The criteria for diagnosing dengue are presented in Figure 2."}}]
    context = format_context(results)
    assert "Fig. 2. Dengue case classification by severity (PDF page 17)" in context


def test_exact_caption_heading_resolves_when_chunk_has_no_figure_number(tmp_path):
    from medrag.generation.generation import format_context
    from medrag.citations.citations import build_citations

    catalog = fixture_catalog(tmp_path)
    payload = {"source": "who", "source_id": "dengue fever", "chunk_id": "classification",
               "raw_text": "Dengue case classification by severity\nDengue case classification by severity\nWarning signs"}
    results = [{"payload": payload}]
    assert "Fig. 2. Dengue case classification by severity" in format_context(results, visual_catalog=catalog)
    citations = build_citations("Classification [1]", results, {})
    output = attach_source_visuals(citations, results, catalog)
    assert output[0]["images"][0]["filename"] == "diagram.png"
    assert revalidate_saved_visuals(output, catalog)[0]["images"] == output[0]["images"]
    for changes in ({"source_id": "another document"}, {"source": "user_upload"},
                    {"raw_text": "The dengue case classification by severity is discussed here."},
                    {"raw_text": "Dengue case classification"}):
        altered = {**payload, **changes}
        assert attach_source_visuals(citations, [{"payload": altered}], catalog)[0]["images"] == []
