# Phase 4: WHO Guidelines Ingestion — Report (Revised)

## Phase Objective

Ingest real WHO clinical guideline documents for the project's 36 topics, extracting not just text but also tables and images — completing the third data source alongside PubMed (research literature) and OpenFDA (structured drug data), and matching the original architecture's multimodal (text + image + table) design.

## What Was Built

- **URL resolution** (`who_client.py`) — `resolve_who_pdf_url()` resolves an old, now-broken WHO IRIS handle (e.g. `10665/344424`) through IRIS's DSpace REST API (handle → item UUID → ORIGINAL bundle → bitstream) into a working direct PDF download URL.
- **Unified per-PDF extraction** (`who_client.py`):
  - `extract_page_content()` — for one page: detects and extracts tables first (via `pdfplumber`), then extracts plain text with those table regions excluded, plus an unmodified raw-text fallback. Table bounding boxes are clamped to page limits to avoid a rare out-of-range coordinate crash.
  - `extract_full_document()` — loops the above across every page of a PDF, aggregating clean text, raw text, all tables, and page count.
  - `extract_images()` — extracts embedded images via `PyMuPDF` (`fitz`), filtering out tiny icons/logos by size.
  - `filter_and_dedupe_images()` — removes images repeated more than 3 times across a document (treated as logo/branding elements, not content), and dedupes any remaining repeats to their first occurrence.
  - `is_blank_or_near_solid()` — detects and drops blank/near-solid-color images (a colorspace/mask extraction artifact that occasionally produces solid black images with no real visual content).
  - `fetch_who_guideline()` — the full per-document pipeline: download → extract text/tables/images → filter/dedupe images → return a validated `Guideline` plus raw tables/images.
- **Data models** (`models.py`) — `Guideline` (now `clean_text`/`raw_text`/`num_tables`/`num_images` instead of a single `full_text`), `WhoTable` (page + row/column data), `WhoImage` (page + filename + dimensions).
- **Storage** (`storage.py`) — `save_who_tables`/`load_who_tables` and `save_who_images`/`load_who_images` added; existing `save_guideline`/`load_guideline` needed no changes (schema-agnostic serialization).
- **Runner script** (`run_who_ingestion.py`) — rebuilt to call the unified pipeline and save all three outputs (guideline, tables, images) per topic, with the corrected header/footer stripping pattern as the default.

## Key Design Decisions

1. **Redesigned as one unified extraction pass rather than three separate phases.** The original plan (Image Extraction, then Table Extraction, then a retroactive text cleanup) was replaced with a single combined pass per PDF: detect tables first, extract clean text excluding those regions, extract images separately — avoiding rework and the need to patch already-ingested text later.
2. **Treated this as a revision of Phase 4 itself, not a new phase** — since the unified extraction directly replaces and improves Phase 4's own text output, rather than adding new scope beyond it.
3. **Switched from `pypdf` to `pdfplumber` (text/tables) and `PyMuPDF` (images).** A verification pass on the original `pypdf`-based extraction confirmed prose text was clean, but tables were badly flattened/garbled (e.g. GRADE evidence tables in the malaria and breast cancer guidelines came out as jumbled fragments) — `pypdf` has no concept of table structure at all.
4. **Kept both `clean_text` and `raw_text`.** `pdfplumber`'s bbox-based table exclusion is a rectangle, not a precise cell boundary — on dense, table-heavy pages it can also remove legitimate nearby prose (captions, footnotes, references) that happens to fall within a table's bounding box. Rather than engineering a more precise (and riskier) cell-level exclusion, both versions are stored: `clean_text` as the primary field for chunking/embedding, `raw_text` as an unmodified fallback so nothing is ever truly lost.
5. **Deduplicated shared documents by URL, not by topic.** Several topics intentionally share one source document (asthma/copd via the PEN package; coronary artery disease/heart failure/stroke/hyperlipidemia via the CVD risk guideline; depression/anxiety disorder/epilepsy via mhGAP) — each unique PDF is downloaded and extracted only once, then its results are re-saved under every topic name that references it.
6. **Re-verified the 24/12 topic coverage split** (24 topics with real WHO guidance, 12 confirmed gaps) with broader, non-IRIS-restricted searches after discovering some WHO documents live on `cdn.who.int` rather than `iris.who.int` — confirmed the gap topics (osteoarthritis, rheumatoid arthritis, osteoporosis, chronic kidney disease, lung cancer, peptic ulcer disease, irritable bowel syndrome, arrhythmia, hypothyroidism, hyperthyroidism, migraine, Parkinson's disease) are genuinely outside WHO's guideline scope, not a search-bias artifact.
7. **Filtered repeated logo images and blank extraction artifacts rather than keeping everything.** Initial image extraction pulled the same branding graphic (e.g. the mhGAP logo) dozens of times per document, plus occasional solid-black images from a mask/colorspace artifact — both would have wasted Phase 8 embedding compute and polluted retrieval with meaningless near-duplicate vectors. Chose hash-based repeat detection (drop anything repeating >3 times) plus a simple pixel-standard-deviation blank check, over more complex perceptual-hashing or ML-based approaches, since the goal was removing obvious noise, not achieving perfect image classification.
8. **Added full-page rasterization for vector-drawn figures.** `PyMuPDF`'s embedded-image extraction only captures actual embedded bitmap objects — it cannot see vector-drawn diagrams, flowcharts, or algorithms (common in clinical guidelines, e.g. "Fig. 1: Analytic framework," "Algorithm 1/2"), since those are drawn with PDF vector instructions, not stored as image objects. Solved by detecting figure/algorithm captions in the extracted text and rendering those specific pages as full images via `PyMuPDF`'s `get_pixmap()` — capturing the diagram exactly as it visually appears, including its own labels and text (which is necessary for the diagram to be meaningful on its own, not treated as unwanted duplication of the separately-stored prose text). Rasterization is skipped for pages that already yielded a real embedded image, to avoid redundant near-duplicate content. A new `image_type` field (`"embedded"` vs `"rasterized_page"`) distinguishes the two in saved metadata.

## Results

- **24/24 topics** successfully processed in the final production run (17 unique documents).
- **~1,204 tables** extracted in total across all documents.
- Text extraction verified dramatically cleaner than the original `pypdf` output — structured rows/columns instead of flattened, unreadable fragments; repeated document headers stripped from both `clean_text` and `raw_text`.
- Image extraction reduced from ~300 mostly-duplicate files (some topics had 20+ repeats of a single logo) down to a clean, mostly-unique set of real figures per topic (roughly 0-8 each) — genuine content came through clearly (e.g. a malaria milestones/targets chart, dengue fever context photos, COVID-19 diagrams, hepatitis patient photos).
- Full-page rasterization now additionally captures vector-drawn figures/algorithms that embedded-image extraction alone would have missed entirely (e.g. hypertension's treatment algorithms), tagged with `image_type="rasterized_page"` to distinguish from real embedded images.
- A small number of low-impact artifacts remain (an occasional single ISBN barcode graphic or single WHO emblem logo per document) — judged not worth further filtering given their minimal impact on embedding quality at this scale.

## Challenges & Solutions

- **WHO's IRIS repository migrated to a JavaScript-based DSpace 7 frontend**, breaking every old-style `apps.who.int/iris/bitstream/handle/...` URL. Solved via the handle → item → bundle → bitstream resolution chain against IRIS's (unofficial, reverse-engineered) REST API — a known risk for any future re-run if WHO changes their API again, though it doesn't affect data already ingested.
- **`pdfplumber`'s Pillow dependency conflicted with Streamlit's pinned version** (`pillow<11` vs. `pdfplumber 0.11.10`'s new `Pillow>=12.2.0` requirement). Resolved by pinning an earlier, compatible `pdfplumber==0.11.4` release instead of fighting the latest version.
- **Function-versioning confusion during notebook debugging** — redefining the same function name multiple times while iterating (adding `raw_text`, then bbox clamping) meant the *last-executed* version silently became active, regardless of file position; an out-of-order re-run left an outdated 3-return-value version active when the batch expected 4, causing an `unpack` error. Solved by consolidating to one final, authoritative cell per function, run immediately before the batch.
- **Table bounding boxes occasionally exceeded page boundaries** (a PDF rendering/rounding quirk), crashing `outside_bbox()`. Fixed by clamping each box to the page's actual dimensions before use.
- **Bbox-based table exclusion also removes some legitimate nearby prose** on table-dense pages (rectangles don't perfectly match table shapes). Accepted as a known tradeoff, mitigated by keeping the unmodified `raw_text` as a fallback rather than engineering fragile cell-level precision.
- **The header/footer stripping pattern initially only matched page-number footers**, missing the repeated WHO branding header line present on every page — leaving that noise in the saved text. Fixed with a combined pattern matching any line containing "World Health Organization (WHO)" plus the page-number footer, and re-ran the full batch to overwrite the saved files with corrected text.
- **Most extracted images turned out to be a repeated logo/branding graphic** (e.g. the mhGAP logo appearing ~27 times in one document), plus occasional blank/solid-black images from a mask-extraction artifact. An initial cleanup attempt (patching only the metadata-listed files) missed dozens of orphaned image files left over from before the fix was applied, since they were no longer referenced in the updated metadata at all. Resolved by wiping the entire `data/images/who/` folder and re-running the full ingestion batch fresh with `filter_and_dedupe_images()` and `is_blank_or_near_solid()` now applied at the source.

## Files Created

- `notebooks/phase04_who_guidelines.ipynb`
- `backend/src/medrag/ingestion/who_client.py` (resolver + unified extraction + image filtering)
- `backend/src/medrag/ingestion/models.py` (updated — `Guideline` revised, `WhoTable`/`WhoImage` added, `WhoImage.image_type` added)
- `backend/src/medrag/ingestion/storage.py` (updated — table/image save/load functions added)
- `backend/scripts/run_who_ingestion.py` (rebuilt for the unified pipeline)
- `backend/requirements.txt` (updated — added `pdfplumber==0.11.4`, `pymupdf==1.28.0`)
- `data/raw/who/*.json` (24 files — clean_text, raw_text, counts)
- `data/tables/who/*.jsonl` (24 files — ~1,204 tables total)
- `data/images/who/*.png` + `*_metadata.jsonl` (24 topics — clean, deduplicated real images)
- `docs/phase04_report.md`