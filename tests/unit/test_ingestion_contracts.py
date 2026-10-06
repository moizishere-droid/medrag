"""Offline source ingestion and extraction checks; no source downloads."""
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import fitz
import pytest
from PIL import Image

from medrag.ingestion import pipeline, pubmed_client as pm, openfda_client as fda, who_client as who
from medrag.ingestion.models import Article


def test_pubmed_parses_missing_language_medline_date_and_collective_author():
    raw = {"MedlineCitation": {"PMID": "12", "Article": {
        "ArticleTitle": "Trial", "Abstract": {"AbstractText": ["First", "Second"]},
        "AuthorList": [{"CollectiveName": "Study group"}],
        "Journal": {"Title": "Journal", "JournalIssue": {"PubDate": {"MedlineDate": "2025 Winter"}}},
    }}}
    article = pm.parse_article(raw, "diabetes")
    assert (article.language, article.pub_date, article.abstract, article.authors) == ("unknown", "2025 Winter", "First Second", ["Study group"])
    parsed, failures = pm.parse_articles_safe([raw, {}], "diabetes")
    assert parsed == [article] and len(failures) == 1


def test_pubmed_target_count_skips_existing_and_caps_new_articles(monkeypatch):
    article = Article(pmid="2", title="Trial", abstract="Evidence", authors=[], journal="J", pub_date="2025", language="eng", topic="diabetes", url="https://pubmed.ncbi.nlm.nih.gov/2/")
    monkeypatch.setattr(pipeline, "get_existing_pmids", lambda *a: {"1"})
    search = Mock(return_value=["1", "2", "3"])
    fetch = Mock(return_value={"PubmedArticle": [article]})
    save = Mock()
    monkeypatch.setattr(pipeline, "search_pubmed", search)
    monkeypatch.setattr(pipeline, "fetch_articles_raw", fetch)
    monkeypatch.setattr(pipeline, "parse_articles_safe", lambda rows, topic: (rows, []))
    monkeypatch.setattr(pipeline, "save_articles", save)
    monkeypatch.setattr(pipeline, "rate_limit_delay", lambda **k: None)
    assert pipeline.ingest_topic("diabetes", "unused", target_count=1)["fetched"] == 0
    search.assert_not_called()
    assert pipeline.ingest_topic("diabetes", "unused", target_count=2)["fetched"] == 1
    fetch.assert_called_once_with(["2"])
    save.assert_called_once_with([article], topic="diabetes", output_dir="unused")


def test_openfda_search_is_quoted_and_real_no_results_is_empty(monkeypatch):
    get = Mock(return_value=SimpleNamespace(status_code=404))
    monkeypatch.setattr(fda.requests, "get", get)
    assert fda.fetch_drugs_raw("hiv aids", search_term="HIV-1 infection", api_key="test") == []
    assert get.call_args.kwargs["params"] == {"search": 'indications_and_usage:"HIV-1 infection"', "limit": 150, "api_key": "test"}


def test_openfda_parser_and_deduplication():
    drug = fda.parse_drug_record({"openfda": {"generic_name": ["Metformin"]}, "indications_and_usage": ["One.", "Two."]}, "diabetes")
    assert drug.brand_name == drug.generic_name == "Metformin"
    assert drug.indications_and_usage == "One. Two."
    assert fda.dedupe_drugs([drug, drug.model_copy(update={"brand_name": " METFORMIN "})]) == [drug]


def test_who_url_resolution_traverses_original_bundle(monkeypatch):
    responses = [
        {"uuid": "item"},
        {"_embedded": {"bundles": [{"name": "ORIGINAL", "_links": {"bitstreams": {"href": "https://example.org/streams"}}}]}},
        {"_embedded": {"bitstreams": [{"_links": {"content": {"href": "https://example.org/document.pdf"}}}]}},
    ]
    get = Mock(side_effect=[SimpleNamespace(status_code=200, json=lambda data=data: data) for data in responses])
    monkeypatch.setattr(who.requests, "get", get)
    assert who.resolve_who_pdf_url("10665/123") == "https://example.org/document.pdf"
    assert get.call_count == 3


@pytest.fixture
def tiny_pdf():
    with fitz.open() as doc:
        page = doc.new_page()
        page.insert_text((50, 50), "Figure 1. Medical evidence.")
        return doc.tobytes()


def test_who_real_pdf_extraction_and_vector_figure_rendering(tiny_pdf):
    clean, raw, tables, pages, figure_pages = who.extract_full_document(tiny_pdf)
    assert "Medical evidence" in clean and raw == clean
    assert tables == [] and pages == 1 and figure_pages == [0]
    assert who.extract_images(tiny_pdf) == []
    rendered = who.rasterize_figure_pages(tiny_pdf, [0, 99])
    assert len(rendered) == 1 and rendered[0]["width"] > 0
    with Image.open(BytesIO(rendered[0]["image_bytes"])) as image:
        image.verify()


def test_who_full_pipeline_rasterizes_caption_pages(monkeypatch, tiny_pdf):
    monkeypatch.setattr(who.requests, "get", lambda *a, **k: SimpleNamespace(content=tiny_pdf, raise_for_status=lambda: None))
    guideline, tables, images = who.fetch_who_guideline("diabetes", "https://example.org/doc.pdf", "Guide")
    assert guideline.num_pages == 1 and guideline.num_images == 1 and tables == []
    assert images[0]["image_type"] == "rasterized_page"


def test_who_repeated_logos_and_solid_images_are_removed():
    def png(color):
        with Image.new("RGB", (10, 10), color) as image:
            image.putpixel((0, 0), (255, 255, 255))
            output = BytesIO()
            image.save(output, format="PNG")
            return output.getvalue()
    logo, unique, blank = png("black"), png("red"), png("white")
    inputs = [{"image_bytes": logo}] * 4 + [{"image_bytes": unique}] * 2 + [{"image_bytes": blank}]
    assert who.filter_and_dedupe_images(inputs) == [{"image_bytes": unique}]
