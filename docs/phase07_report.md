# Phase 7: Image Embeddings — Report

## Phase Objective

Generate CLIP embeddings for all real, deduplicated WHO images (extracted in Phase 4), enabling visual similarity search as a secondary retrieval channel alongside the text embeddings from Phase 6.

## What Was Built

- **CLIP loading** (`image_embedder.py`) — `get_clip_model()` loads `ViT-B-32` (OpenAI pretrained weights) once, runs locally on CPU (no GPU needed at this scale — ~76 images, small model).
- **Image deduplication** (`deduplicate_images()`) — same content-hash dedup principle used for text chunks/drugs/articles in Phase 6, since WHO images are saved per-topic and shared documents (asthma/copd, the CVD group, mhGAP) produce identical image files across topic folders.
- **Cover-page exclusion rule** — a special case discovered during this phase: images at the cover-page position (`*_page0_img0.png`) are deliberately **excluded** from cross-topic hash-based merging, even when their content hash matches another document's cover graphic, since that reflects two unrelated documents sharing the same WHO PDF template — not real shared content.
- **`embed_image()` / `embed_who_images()`** — the full pipeline: deduplicate across all topic files → embed each unique image once with CLIP → return embeddings alongside each image's full topic list.
- **Storage** (`storage.py` additions) — `save_image_embeddings()`/`load_image_embeddings()`, saving a `.npy` array plus a JSONL index (filename, topics, page number, image type) — same pattern as text embeddings.
- **Runner script** (`run_image_embeddings.py`) — production entry point across all 24 WHO topics.

## Key Design Decisions

1. **CLIP (ViT-B-32) chosen over alternatives** — the standard, well-established choice for this task, already scoped in the original Phase 0 architecture (`open-clip-torch`).
2. **Runs locally, no API cost** — unlike text embeddings (OpenAI API), image embeddings run entirely on-device; no cost tracking needed for this phase.
3. **Deduplication applied before embedding**, mirroring the exact fix pattern already validated three times in Phase 6 (WHO chunks, OpenFDA drugs, PubMed articles) — the same underlying image should never be embedded more than once just because it's saved under multiple topic folders.
4. **Cover-page images excluded from cross-topic merging as a general rule**, not just a one-off fix — discovered when `pneumonia_page0_img0.png` was found to coincidentally content-hash-match `malnutrition`'s cover graphic, despite the two documents being completely unrelated. Merging them would have created a false semantic link (an image "shared" between pneumonia and malnutrition with no real connection). The fix generalizes to any future document pair using the same WHO cover template.
5. **CLIP's known limitation for this project was tested and confirmed, not just assumed.** CLIP resizes every image to 224×224 before embedding — enough to capture general visual layout/style, but not to read dense paragraph text on a rasterized document page. A same-document similarity test (two images from the asthma/copd document) scored 0.7346, versus 0.5482 for a cross-document pair (asthma vs. hypertension) — real, directionally correct signal, but a modest gap, since WHO document pages share a broadly similar visual style regardless of actual content. This is documented as an honest limitation rather than an unqualified success.
6. **Image embeddings are a secondary, visual-similarity channel, not the primary retrieval path for images.** Given CLIP's text-reading weakness on this project's largely text-heavy medical figures, the plan is for image *captions* (extracted alongside the text in Phase 6) to carry the primary semantic signal, with CLIP similarity supplementing rather than replacing that.

## Results

- **100 total image entries** across 24 WHO topic files reduced to **76 truly unique images** after content-hash deduplication with the cover-page exclusion rule applied.
- All 76 unique images successfully embedded with CLIP — 0 failures, 512-dimension output confirmed for every image.
- Similarity sanity check passed: same-document images scored meaningfully higher (0.7346) than cross-document images (0.5482), confirming the embeddings capture real, if modest, visual signal.

## Challenges & Solutions

- **A false cross-document image match was found and fixed.** `pneumonia_page0_img0.png` and `malnutrition`'s cover image shared an identical content hash despite being from unrelated documents — traced to both using the same generic WHO PDF cover template. Fixed by excluding all `*_page0_img0.png`-pattern filenames from cross-topic hash merging, treating them as topic-local regardless of content match.
- **CLIP's text-reading limitation was measured, not assumed.** Rather than taking the "CLIP is weak on dense document text" concern on faith, a same-document vs. cross-document similarity test was run and confirmed the effect is real but modest — informing the decision to treat image embeddings as secondary to caption-based retrieval.

## Known Follow-Up (Not Yet Implemented)

An image-to-chunk linking step was planned during this phase's design discussion — matching each `WhoImage` to its nearby text chunk(s) by figure-caption string matching (e.g. locating "Figure 2" inside a chunk's `raw_text`), since the `Chunk` model currently has no `page` field (WHO text is chunked from the fully merged `clean_text`, so page boundaries aren't preserved in chunk metadata). This linking would let a retrieved image inherit its caption's real semantic content for ranking, rather than relying on CLIP similarity alone. **This step has been designed but not yet added to production code** — planned as a near-term follow-up rather than blocking the rest of the phase.

## Files Created

- `notebooks/phase07_image_embeddings.ipynb`
- `backend/src/medrag/embeddings/image_embedder.py` (`get_clip_model`, `deduplicate_images`, `embed_image`, `embed_who_images`)
- `backend/src/medrag/embeddings/storage.py` (updated — `save_image_embeddings`/`load_image_embeddings` added)
- `backend/scripts/run_image_embeddings.py`
- `data/processed/embeddings/who_images_embeddings.npy` (76 unique image vectors, 512-dim)
- `data/processed/embeddings/who_images_index.jsonl` (filename, topics, page number, image type per row)
- `docs/phase07_report.md`