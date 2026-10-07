"""Prepare source-page renders from explicit captions; review before publishing.

No network or database writes. Input must be the original guideline PDF.
The manifest is the sole authority for figure display, including old chat links.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

import fitz

CAPTION = re.compile(r"^\s*Fig(?:ure)?\.?\s*(\d+(?:\.\d+)*[a-z]?)[.:]?\s+([A-Z][^\n]+)$")


def prepare_figures(pdf_path, source_id, output_dir, source_url):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    source_hash = hashlib.sha256(Path(pdf_path).read_bytes()).hexdigest()
    candidates = {}
    with fitz.open(pdf_path) as document:
        for page_number, page in enumerate(document):
            for line in page.get_text().splitlines():
                match = CAPTION.match(line)
                if match:
                    number = match[1].lower()
                    candidates.setdefault(number, []).append((page_number, line.strip()))
        records = []
        for number, matches in candidates.items():
            # Repeated captions (e.g. contents plus body) are ambiguous. Review
            # those manually instead of treating the first occurrence as truth.
            if len(matches) != 1:
                continue
            page_number, caption = matches[0]
            safe_source = re.sub(r"[^a-zA-Z0-9_-]", "_", source_id)
            safe_number = number.replace(".", "_")
            name = f"{safe_source}_page{page_number}_verified_fig{safe_number}.png"
            path = output_dir / name
            document[page_number].get_pixmap(dpi=150).save(path)
            records.append({"source_id": source_id, "figure_number": number,
                            "filename": name, "page_number": page_number,
                            "caption": caption, "image_type": "rasterized_page",
                            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                            "source_pdf_sha256": source_hash, "source_url": source_url})
    manifest = output_dir / "verified_figures.jsonl"
    existing = [json.loads(line) for line in manifest.read_text(encoding="utf-8").splitlines() if line.strip()] if manifest.exists() else []
    existing = [record for record in existing if record["source_id"] != source_id]
    manifest.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in existing + records), encoding="utf-8")
    return records


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", required=True)
    parser.add_argument("--source-id", required=True, help="Exact canonical WHO source_id in Qdrant")
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--output-dir", default=str(Path(__file__).resolve().parents[2] / "data/images/who"))
    args = parser.parse_args()
    rows = prepare_figures(args.pdf, args.source_id, args.output_dir, args.source_url)
    print(f"Prepared {len(rows)} caption/page mappings. Visually review source renders before deployment.")
    for row in rows:
        print(f"Figure {row['figure_number']}: PDF page {row['page_number'] + 1}: {row['filename']}")
