"""Resolve visuals from cited WHO evidence, never from arbitrary user paths."""
import json
import logging
import hashlib
import re
from functools import lru_cache
from pathlib import Path
from medrag.processing.image_linking import extract_figure_references, is_figure_listing_chunk

logger = logging.getLogger(__name__)


def table_text(rows):
    return "\n".join(" | ".join("" if cell is None else str(cell) for cell in row) for row in rows)


TABLE_WARNING = "This source table could not be extracted reliably. Check the cited PDF for the original table."


def readable_table(rows):
    """Reject damaged glyphs and collapsed multi-column extraction without guessing cells."""
    if not isinstance(rows, list) or not rows or not all(isinstance(row, list) for row in rows):
        return False
    text = table_text(rows)
    if re.search(r"\(cid:\d+\)", text) or "\ufffd" in text:
        return False
    columns = {i for row in rows for i, cell in enumerate(row) if cell is not None and str(cell).strip()}
    width = max(map(len, rows), default=0)
    return bool(columns) and (width <= 1 or len(columns) >= 2)


class VisualCatalog:
    """Read-only manifest for the curated artifacts bundled with the backend."""

    def __init__(self, data_root):
        self.image_root = (Path(data_root) / "images" / "who").resolve()
        self.images = {}
        self.figures = {}
        self.verified_names = set()
        self.tables = {}
        for path in sorted(self.image_root.glob("*_metadata.jsonl")):
            for record in self._records(path):
                name = record.get("filename", "")
                if self._safe_image_path(name) is not None:
                    self.images[name] = record
        for record in self._records(self.image_root / "verified_figures.jsonl"):
            name = record.get("filename", "")
            path = self._safe_image_path(name)
            if (path is None or not record.get("source_id") or not record.get("figure_number")
                    or not record.get("caption") or not record.get("sha256")):
                continue
            if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
                logger.warning("Verified figure content changed: %s", name)
                continue
            self.images[name] = record
            self.verified_names.add(name)
            self.figures[(record["source_id"], str(record["figure_number"]))] = record
        for path in sorted((Path(data_root) / "tables" / "who").glob("*.jsonl")):
            for record in self._records(path):
                rows = record.get("table_data")
                if isinstance(rows, list) and rows and all(isinstance(row, list) for row in rows):
                    key = (record.get("topic"), record.get("page_number"), table_text(rows))
                    self.tables[key] = rows

    @staticmethod
    def _records(path):
        try:
            return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except (OSError, ValueError):
            logger.warning("Could not read curated visual manifest %s", path.name)
            return []

    def _safe_image_path(self, name):
        if not isinstance(name, str) or not name or "/" in name or "\\" in name or ":" in name:
            return None
        if Path(name).suffix.lower() != ".png":
            return None
        path = (self.image_root / name).resolve()
        return path if path.parent == self.image_root and path.is_file() else None

    def image_path(self, name):
        return self._safe_image_path(name) if name in self.verified_names else None

    def table(self, payload):
        metadata = payload.get("metadata") or {}
        raw = payload.get("raw_text", "")
        rows = metadata.get("table_data")
        # Future indexes retain cells directly; old indexes resolve exact text
        # against the saved source rows. Never guess cell boundaries or headers.
        if not (isinstance(rows, list) and rows and all(isinstance(row, list) for row in rows)
                and (table_text(rows) == raw or raw.endswith(": " + table_text(rows)))):
            rows = None
            for topic in payload.get("source_id", "").split("+"):
                rows = self.tables.get((topic, metadata.get("page_number"), raw))
                if rows is not None:
                    break
        if rows is None or not readable_table(rows):
            return None
        return {"rows": [["" if cell is None else str(cell) for cell in row] for row in rows],
                "page_number": metadata.get("page_number"),
                "part": metadata.get("table_part")}


@lru_cache(maxsize=2)
def get_visual_catalog(data_root):
    return VisualCatalog(data_root)


def attach_source_visuals(citations, results, catalog):
    """Only cited, already-scoped retrieval results supply visual evidence.

    WHO assets are curated and shared. Private uploads never resolve through
    this curated catalog. Keep the attachments inside persisted citation JSON.
    """
    images_seen = set()
    tables_seen = set()
    output = []
    for citation in citations:
        entry = {**citation, "table": None, "table_warning": None, "images": []}
        payload = results[citation["marker"] - 1]["payload"]
        if payload.get("source") == "who":
            if payload.get("chunk_type") == "table" and len(tables_seen) < 3:
                table = catalog.table(payload)
                if table is None:
                    entry["table_warning"] = TABLE_WARNING
                if table and payload["chunk_id"] not in tables_seen:
                    entry["table"] = table
                    tables_seen.add(payload["chunk_id"])
            references = figure_references(payload, catalog)
            entry["images"] = resolve_figures(payload.get("source_id"), references, catalog, images_seen)
        output.append(entry)
    return output


def figure_references(payload, catalog):
    """Resolve figure labels or an exact standalone verified caption heading.

    PDF chunking can separate the figure number from its caption and cells.
    Only complete heading lines in the same curated document may recover it;
    substring/keyword matches and table-of-figures listings are excluded.
    """
    raw = payload.get("raw_text", "")
    if payload.get("source") != "who" or is_figure_listing_chunk(raw):
        return []
    references = extract_figure_references(raw)
    normalize = lambda value: " ".join(value.split()).casefold()
    lines = {normalize(line) for line in raw.splitlines() if line.strip()}
    headings = {}
    for (source_id, number), record in catalog.figures.items():
        if source_id != payload.get("source_id"):
            continue
        heading = re.sub(r"^\s*Fig(?:ure)?\.?\s*\d+(?:\.\d+)*[a-z]?[.:]?\s+", "", record["caption"], flags=re.I)
        headings.setdefault(normalize(heading), []).append(number)
    for heading, numbers in headings.items():
        if heading in lines and len(numbers) == 1 and numbers[0] not in references:
            references.append(numbers[0])
    return references


def resolve_figures(source_id, numbers, catalog, seen):
    images = []
    for number in numbers:
        record = catalog.figures.get((source_id, str(number)))
        if not record or record["filename"] in seen or len(seen) >= 3:
            continue
        name = record["filename"]
        if catalog.image_path(name) is None:
            continue
        images.append({"filename": name, "page_number": record.get("page_number"),
                       "figure_number": str(number), "image_type": record.get("image_type", "rasterized_page"),
                       "caption": record["caption"]})
        seen.add(name)
    return images


def revalidate_saved_visuals(citations, catalog):
    """Replace stale ordinal links in history with verified source mappings."""
    seen = set()
    output = []
    for citation in citations or []:
        entry = dict(citation)
        if entry.get("table") and not readable_table(entry["table"].get("rows")):
            entry["table"] = None
            entry["table_warning"] = TABLE_WARNING
        references = [image.get("figure_number") for image in citation.get("images", []) if isinstance(image, dict)]
        references += [image.get("figure_number") for image in citation.get("linked_images", []) if isinstance(image, dict)]
        entry["images"] = resolve_figures(citation.get("source_id"), references, catalog, seen) if citation.get("source") == "who" else []
        output.append(entry)
    return output
