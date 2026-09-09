# Phase 7: Image Embeddings — Report

## Phase Objective

Generate CLIP embeddings for all real, deduplicated WHO images (extracted in Phase 4), enabling visual similarity search as a secondary retrieval channel alongside the text embeddings from Phase 6. Also link each image to the text chunk(s) that reference it, so a retrieved image can inherit its surrounding prose's real semantic content for ranking, rather than relying on CLIP similarity alone.

## What Was Built

- **CLIP loading** (`image_embedder.py`) — `get_clip_model()` loads `ViT-B-32` (OpenAI pretrained weights) once, runs locally on CPU (no GPU needed at this scale — ~76 images, small model).
- **Image deduplication** (`deduplicate_images()`) — same content-hash dedup principle used for text chunks/drugs/articles in Phase 6, since WHO images are saved per-topic and shared documents (asthma/copd, the CVD group, mhGAP) produce identical image files across topic folders.
- **Cover-page exclusion rule** — a special case discovered during this phase: images at the cover-page position (`*_page0_img0.png`) are deliberately **excluded** from cross-topic hash-based merging, even when their content hash matches another document's cover graphic, since that reflects two unrelated documents sharing the same WHO PDF template — not real shared content.
- **`embed_image()` / `embed_who_images()`** — the full pipeline: deduplicate across all topic files → embed each unique image once with CLIP → return embeddings alongside each image's full topic list.
- **Storage** (`storage.py` additions) — `save_image_embeddings()`/`load_image_embeddings()`, saving a `.npy` array plus a JSONL index (filename, topics, page number, image type) — same pattern as text embeddings.
- **Runner script** (`run_image_embeddings.py`) — production entry point across all 24 WHO topics.
- **Image-to-chunk linking** (`image_linking.py`) — added as a completion of this phase's originally-flagged follow-up (see below): matches each image to the WHO text chunk(s) that reference it, via figure-caption string matching, with a filter to exclude List-of-Figures/table-of-contents style chunks from producing false links (see Challenges & Solutions).

## Key Design Decisions

1. **CLIP (ViT-B-32) chosen over alternatives** — the standard, well-established choice for this task, already scoped in the original Phase 0 architecture (`open-clip-torch`).
2. **Runs locally, no API cost** — unlike text embeddings (OpenAI API), image embeddings run entirely on-device; no cost tracking needed for this phase.
3. **Deduplication applied before embedding**, mirroring the exact fix pattern already validated three times in Phase 6 (WHO chunks, OpenFDA drugs, PubMed articles) — the same underlying image should never be embedded more than once just because it's saved under multiple topic folders.
4. **Cover-page images excluded from cross-topic merging as a general rule**, not just a one-off fix — discovered when `pneumonia_page0_img0.png` was found to coincidentally content-hash-match `malnutrition`'s cover graphic, despite the two documents being completely unrelated. Merging them would have created a false semantic link (an image "shared" between pneumonia and malnutrition with no real connection). The fix generalizes to any future document pair using the same WHO cover template.
5. **CLIP's known limitation for this project was tested and confirmed, not just assumed.** CLIP resizes every image to 224×224 before embedding — enough to capture general visual layout/style, but not to read dense paragraph text on a rasterized document page. A same-document similarity test (two images from the asthma/copd document) scored 0.7346, versus 0.5482 for a cross-document pair (asthma vs. hypertension) — real, directionally correct signal, but a modest gap, since WHO document pages share a broadly similar visual style regardless of actual content. This is documented as an honest limitation rather than an unqualified success.
6. **Image embeddings are a secondary, visual-similarity channel, not the primary retrieval path for images.** Given CLIP's text-reading weakness on this project's largely text-heavy medical figures, image *captions* were intended to carry the primary semantic signal — realized in this phase via chunk-based linking rather than a separate captioning model (see point 8).
7. **No new fields added to `Chunk` or `WhoImage` for linking.** The link uses two facts that already existed in the data: `Chunk.source_id` is already the canonical document id (`"+".join(sorted(topics))`, set in Phase 6's `chunk_who_guideline`), and WHO image filenames already encode page and in-page index (`*_page{P}_img{I}.png`). Both models are used exactly as Phase 6/7 left them.
8. **Ordinal figure matching, not position/page matching.** WHO `clean_text` has no page boundaries preserved — text is chunked from the fully merged document. A chunk can't be matched to "the image on the same page" because chunks don't know their page. Instead, images are sorted into each document's extraction order (page, then in-page index), and a "Figure N" mention is matched to the Nth image from that same document — since WHO figures are numbered sequentially in reading order, and PyMuPDF extracts images in that same reading order. This is a heuristic and is documented as one: it rests on figures being numbered sequentially without gaps, and on an image's topic set matching its guideline's topic set exactly.
9. **No fallback for images with zero figure mentions.** A nearest-chunk-by-topic fallback was considered and rejected: with no page metadata on chunks, "nearest" has no reliable meaning and would produce confident-looking but unfounded links. An image with no textual "Figure N" reference anywhere in its document is simply left unlinked, and reported as such.
10. **List-of-Figures / table-of-contents chunks are explicitly filtered out, not just flagged.** Initial spot-checking found that a chunk listing "Fig. 1 ... Fig. 2 ... Fig. 3 ..." (a document's front-matter contents page) matched every ordinal it listed, producing confident-looking but semantically empty links to unrelated images. Rather than leave this as a documented limitation, `is_figure_listing_chunk()` was added to skip any chunk containing 3+ distinct figure/table ordinal numbers before ordinal matching runs. The threshold is set above 2 (not at 2) so a legitimate passage that cross-references two figures in the same paragraph isn't wrongly excluded. This is still a heuristic, not a certainty, and is documented as such.

## Results

**Embeddings:**
- **100 total image entries** across 24 WHO topic files reduced to **76 truly unique images** after content-hash deduplication with the cover-page exclusion rule applied.
- All 76 unique images successfully embedded with CLIP — 0 failures, 512-dimension output confirmed for every image.
- Similarity sanity check passed: same-document images scored meaningfully higher (0.7346) than cross-document images (0.5482), confirming the embeddings capture real, if modest, visual signal.

**Image-to-chunk linking:**
- **4,804 unique WHO chunks** (deduped from per-topic files) checked against the 76 unique images.
- **55 figure mentions found**, all 55 matched to an image within their document's expected image count — **0 out-of-range mentions**, meaning the sequential-numbering assumption held across all 24 WHO documents with no violations.
- **1 List-of-Figures chunk correctly excluded** before matching — a front-matter contents-page chunk (`hypertension_who_text_4`) that listed six figure numbers in sequence, which would otherwise have produced six confident-looking but bogus links to unrelated images on unrelated pages.
- **55 links created, spanning 22 of 76 unique images (~29%)** — the remaining ~71% have no inline "Figure N" textual reference anywhere in their document's chunks (expected for cover graphics, decorative WHO template art, and page-rendered diagrams without inline callouts).
- **0 documents had images but no matching chunks** — the independently-computed canonical id on the image side and chunk side lined up perfectly across every document.
- **Verification after the fix**: the three images previously mis-linked to the excluded ToC chunk (hypertension figures 1–3, pages 2/5/14) were individually re-checked and confirmed to each carry a legitimate, distinct link from real body-text chunks instead — confirming the fix corrected the links rather than simply removing them.
- Spot-checked sample confirmed page numbers increase monotonically with figure number in the hypertension document (page 2 → 5 → 14 → 20 → 37), as the ordinal-matching design predicts.

## Challenges & Solutions

- **A false cross-document image match was found and fixed.** `pneumonia_page0_img0.png` and `malnutrition`'s cover image shared an identical content hash despite being from unrelated documents — traced to both using the same generic WHO PDF cover template. Fixed by excluding all `*_page0_img0.png`-pattern filenames from cross-topic hash merging, treating them as topic-local regardless of content match.
- **CLIP's text-reading limitation was measured, not assumed.** Rather than taking the "CLIP is weak on dense document text" concern on faith, a same-document vs. cross-document similarity test was run and confirmed the effect is real but modest — informing the decision to treat image embeddings as secondary to caption/chunk-based retrieval.
- **No page metadata on chunks ruled out the obvious position-based linking approach.** Solved by using extraction order as a stand-in for figure order instead of page proximity — validated by the 0% out-of-range rate.
- **A List-of-Figures/table-of-contents chunk was found producing bogus links, and fixed rather than just documented.** Distribution checking on the first real run surfaced `hypertension_who_text_4` linking to 6 images from a single chunk — spot-checking its actual text confirmed it was a contents-page listing ("Fig. 1 Analytic framework... 3 / Fig. 2 Framework for analysis... 9 / ..."), not body prose discussing any of those figures. `is_figure_listing_chunk()` was added to exclude chunks with 3+ distinct figure ordinals before matching. Re-running confirmed the fix worked exactly as expected: figure mentions dropped from 61 to 55 (the 6 mentions in the excluded chunk), and the three images that chunk had bogusly linked to were confirmed to have legitimate alternate links from real body chunks instead.

## Known Follow-Up (Not Yet Implemented)

- **The ~71% of images with no figure mentions remain unlinked by design.** No fallback strategy was applied (see Design Decision 9). If image discoverability for these becomes a priority, a captioning-based approach (e.g. vision-language model captioning per image, independent of any chunk text) would be a more principled next step than a chunk-proximity guess.
- **`match_type` is currently always `"ordinal_caption"`** — the field is included in the schema now specifically so a future, more direct matching method (e.g. OCR'd caption text once available) could be added without breaking existing link records.
- **Link records are mention-level, not image-level.** A chunk that mentions the same figure twice produces two identical-looking link rows for that (chunk, image) pair. This is intentional — mention frequency may itself be a useful signal — but downstream consumers (e.g. Qdrant payload construction in a later phase) should deduplicate by `(chunk_id, image_filename)` when building `related_chunk_ids`/`related_image_ids` fields, rather than assuming one row equals one distinct mention.

## Files Created

- `notebooks/phase07_image_embeddings.ipynb`
- `backend/src/medrag/embeddings/image_embedder.py` (`get_clip_model`, `deduplicate_images`, `embed_image`, `embed_who_images`)
- `backend/src/medrag/embeddings/storage.py` (updated — `save_image_embeddings`/`load_image_embeddings` added)
- `backend/scripts/run_image_embeddings.py`
- `backend/src/medrag/processing/image_linking.py` (`extract_figure_references`, `is_figure_listing_chunk`, `group_images_by_document`, `group_chunks_by_document`, `link_images_to_chunks`, `save_image_chunk_links`, `load_image_chunk_links`)
- `backend/scripts/run_image_chunk_linking.py`
- `data/processed/embeddings/who_images_embeddings.npy` (76 unique image vectors, 512-dim)
- `data/processed/embeddings/who_images_index.jsonl` (filename, topics, page number, image type per row)
- `data/processed/embeddings/image_chunk_links.jsonl` (55 link records: chunk_id, point_id, image_filename, figure_number, canonical_id, match_type)
- `docs/phase07_report.md`