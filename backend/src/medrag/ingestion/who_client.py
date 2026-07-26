"""
WHO IRIS guideline client.

IRIS (WHO's document repository) migrated to a JS-based DSpace 7 frontend,
which broke the old apps.who.int/iris/bitstream/handle/... URL pattern
(it now just returns the app shell, not the file). This module resolves
old handles to the correct downloadable bitstream URL via IRIS's REST API:

    handle (10665/XXXXX) -> item UUID -> ORIGINAL bundle -> bitstream content URL

Not every project topic has a dedicated WHO guideline. Where WHO's guidance
is genuinely specialty-society territory instead (e.g. osteoarthritis,
migraine, chronic kidney disease), there is no entry — that is accurate
coverage, not a bug.
"""

import logging
from io import BytesIO
from typing import Optional

import requests
from pypdf import PdfReader

from medrag.ingestion.models import Guideline

logger = logging.getLogger("medrag.ingestion")

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}


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


def fetch_who_guideline(topic: str, url: str, title: str, headers: dict = BROWSER_HEADERS) -> Guideline:
    """
    Download a WHO guideline PDF and extract its full text.
    A browser-like User-Agent is required — WHO's servers return 403 for
    default library user agents.
    """
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()

    pdf_bytes = BytesIO(response.content)
    reader = PdfReader(pdf_bytes)

    full_text = "\n".join(page.extract_text() or "" for page in reader.pages)

    return Guideline(
        title=title,
        topic=topic,
        full_text=full_text,
        num_pages=len(reader.pages),
        source_url=url,
    )