"""
WHO IRIS guideline client: URL resolution + unified text/table/image extraction.

IRIS (WHO's document repository) migrated to a JS-based DSpace 7 frontend,
which broke the old apps.who.int/iris/bitstream/handle/... URL pattern
(it now just returns the app shell, not the file). resolve_who_pdf_url()
resolves old handles to the correct downloadable bitstream URL via IRIS's
REST API:

    handle (10665/XXXXX) -> item UUID -> ORIGINAL bundle -> bitstream content URL

Extraction is unified per-PDF: pdfplumber detects and extracts tables first,
then extracts plain text with those table regions excluded (avoiding the
garbling that plain pypdf-style extraction produces on table-heavy pages).
PyMuPDF (fitz) extracts embedded images separately, since neither pypdf nor
pdfplumber capture those. Repeated logos/branding images (common in headers)
are filtered out via content-hash deduplication.

Not every project topic has a dedicated WHO guideline. Where WHO's guidance
is genuinely specialty-society territory instead (e.g. osteoarthritis,
migraine, chronic kidney disease), there is no entry — that is accurate
coverage, not a bug.
"""

import re
import logging
import hashlib
from collections import Counter
from io import BytesIO
from typing import Optional, List, Tuple, Dict, Any
from PIL import Image
import io as _io

import requests
import pdfplumber
import fitz  # PyMuPDF

from medrag.ingestion.models import Guideline, WhoTable, WhoImage

logger = logging.getLogger("medrag.ingestion")

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}

# Strips the repeated WHO branding header (present on every page, varies by
# document title) and the "N of M" page-number footer.
HEADER_FOOTER_PATTERN = r"(.*World Health Organization \(WHO\).*\n?)|(\d+ of \d+)"


# --- URL resolution -----------------------------------------------------

def resolve_who_pdf_url(handle: str, headers: dict = BROWSER_HEADERS) -> Optional[str]:
    """
    Given an old WHO IRIS handle (e.g. '10665/353829'), resolve it through
    DSpace's REST API to the actual downloadable PDF URL. Returns None if
    resolution fails at any step (missing item, no ORIGINAL bundle, etc.).
    """
    pid_url = f"https://iris.who.int/server/api/pid/find?id=hdl:{handle}"
    r = requests.get(pid_url, headers=headers, timeout=20)
    if r.status_code != 200:
        return None
    item_uuid = r.json()["uuid"]

    bundles_url = f"https://iris.who.int/server/api/core/items/{item_uuid}/bundles"
    r = requests.get(bundles_url, headers=headers, timeout=20)
    if r.status_code != 200:
        return None
    bundles = r.json()["_embedded"]["bundles"]
    original_bundle = next((b for b in bundles if b["name"] == "ORIGINAL"), None)
    if not original_bundle:
        return None

    bitstreams_url = original_bundle["_links"]["bitstreams"]["href"]
    r = requests.get(bitstreams_url, headers=headers, timeout=20)
    if r.status_code != 200:
        return None
    bitstreams = r.json()["_embedded"]["bitstreams"]
    if not bitstreams:
        return None

    return bitstreams[0]["_links"]["content"]["href"]


# --- Text + table extraction (pdfplumber) --------------------------------

def extract_page_content(page, header_footer_pattern: Optional[str] = None) -> Tuple[str, str, List[list]]:
    """
    Extract clean text (tables excluded), raw text (unmodified), and
    structured tables from one page.
    Returns (clean_text, raw_text, tables_list).
    """
    tables_data = []
    text_region = page

    found_tables = page.find_tables()
    for table_obj in found_tables:
        table_rows = table_obj.extract()
        tables_data.append(table_rows)

        x0, top, x1, bottom = table_obj.bbox
        x0 = max(x0, 0)
        top = max(top, 0)
        x1 = min(x1, page.width)
        bottom = min(bottom, page.height)
        safe_bbox = (x0, top, x1, bottom)

        try:
            text_region = text_region.outside_bbox(safe_bbox) if hasattr(text_region, "outside_bbox") else text_region
        except Exception:
            pass

    clean_text = text_region.extract_text() or ""
    raw_text = page.extract_text() or ""

    if header_footer_pattern:
        clean_text = re.sub(header_footer_pattern, "", clean_text).strip()
        raw_text = re.sub(header_footer_pattern, "", raw_text).strip()

    return clean_text, raw_text, tables_data


def extract_full_document(pdf_bytes: bytes, header_footer_pattern: Optional[str] = HEADER_FOOTER_PATTERN):
    """
    Extract clean text, raw text, all tables, and page count from an entire PDF.
    Returns (clean_text, raw_text, all_tables, num_pages).
    """
    pdf_file = BytesIO(pdf_bytes)
    plumber_pdf = pdfplumber.open(pdf_file)

    clean_parts = []
    raw_parts = []
    all_tables = []

    for page_num, page in enumerate(plumber_pdf.pages):
        clean, raw, tables = extract_page_content(page, header_footer_pattern=header_footer_pattern)
        if clean:
            clean_parts.append(clean)
        if raw:
            raw_parts.append(raw)
        for table_data in tables:
            all_tables.append({"page_number": page_num, "table_data": table_data})

    num_pages = len(plumber_pdf.pages)
    return "\n".join(clean_parts), "\n".join(raw_parts), all_tables, num_pages


# --- Image extraction (PyMuPDF) ------------------------------------------

def extract_images(pdf_bytes: bytes, min_width: int = 100, min_height: int = 100) -> List[Dict[str, Any]]:
    """
    Extract embedded images from a PDF, skipping tiny images (likely icons/logos).
    Returns a list of {page_number, image_index, image_bytes, ext, width, height}.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    images = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        image_list = page.get_images(full=True)

        for img_index, img in enumerate(image_list):
            xref = img[0]
            base_image = doc.extract_image(xref)
            width = base_image["width"]
            height = base_image["height"]

            if width < min_width or height < min_height:
                continue

            images.append({
                "page_number": page_num,
                "image_index": img_index,
                "image_bytes": base_image["image"],
                "ext": base_image["ext"],
                "width": width,
                "height": height,
            })

    doc.close()
    return images


def compute_image_hash(image_bytes: bytes) -> str:
    """Hash an image's raw bytes to detect exact duplicates (e.g. repeated logos)."""
    return hashlib.md5(image_bytes).hexdigest()


def is_blank_or_near_solid(image_bytes: bytes, std_threshold: float = 5.0) -> bool:
    """
    Detect blank/near-solid-color images (e.g. black rectangles from a
    mask/alpha-channel extraction artifact) that carry no real visual content.
    Uses pixel standard deviation as a simple, dependency-light heuristic.
    """
    try:

        img = Image.open(_io.BytesIO(image_bytes)).convert("L")  # grayscale
        pixels = list(img.getdata())
        mean = sum(pixels) / len(pixels)
        variance = sum((p - mean) ** 2 for p in pixels) / len(pixels)
        std_dev = variance ** 0.5
        return std_dev < std_threshold
    except Exception:
        return False  # if inspection fails, don't drop the image on that basis


def filter_and_dedupe_images(images: List[Dict[str, Any]], max_repeats: int = 3) -> List[Dict[str, Any]]:
    """
    Remove images that repeat more than max_repeats times across a document
    (treated as logos/branding, not real content), dedupe any remaining
    repeats down to their first occurrence, and drop blank/near-solid-color
    images (extraction artifacts with no real visual content).
    """
    images = [img for img in images if not is_blank_or_near_solid(img["image_bytes"])]

    hashes = [compute_image_hash(img["image_bytes"]) for img in images]
    hash_counts = Counter(hashes)

    seen = set()
    filtered = []
    for img, img_hash in zip(images, hashes):
        if hash_counts[img_hash] > max_repeats:
            continue  # likely a logo/branding element - drop entirely
        if img_hash not in seen:
            seen.add(img_hash)
            filtered.append(img)

    return filtered


# --- Full per-topic pipeline ----------------------------------------------

def fetch_who_guideline(topic: str, url: str, title: str, headers: dict = BROWSER_HEADERS) -> Tuple[Guideline, List[dict], List[dict]]:
    """
    Download a WHO guideline PDF and extract text, tables, and images in one pass.
    Returns (Guideline, tables, images) - tables/images are the raw extraction
    results (not yet converted to WhoTable/WhoImage records or saved to disk).
    """
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    pdf_bytes = response.content

    clean_text, raw_text, tables, num_pages = extract_full_document(pdf_bytes)
    images = extract_images(pdf_bytes)
    images = filter_and_dedupe_images(images)

    guideline = Guideline(
        title=title,
        topic=topic,
        clean_text=clean_text,
        raw_text=raw_text,
        num_pages=num_pages,
        num_tables=len(tables),
        num_images=len(images),
        source_url=url,
    )

    return guideline, tables, images