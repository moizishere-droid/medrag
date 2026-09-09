# Phase 8: Qdrant Vector Database Ingestion — Report

## Phase Objective

Load all embedded data — PubMed, OpenFDA, and WHO text chunks (Phase 6) plus WHO image embeddings and their image-to-chunk links (Phase 7) — into Qdrant, the vector database that will power retrieval starting in the next phase. This is the point where all prior ingestion, chunking, and embedding work becomes actually queryable.

## What Was Built

- **Qdrant client & collection management** (`qdrant_client.py`) — `get_qdrant_client()`, `ensure_collections()` (create-if-missing, non-destructive), `reset_collections()` (explicit drop-and-recreate, opt-in only), `generate_image_point_id()` (deterministic UUID5 from filename).
- **Point-building and upload logic** (`qdrant_ingestion.py`) — `dedupe_links()`, `build_link_maps()`, `build_text_point()`/`build_image_point()`, `upload_points()` (batched), `upload_source_chunks()`, `upload_images()`. Source-agnostic: the same point-building logic handles PubMed, OpenFDA, and WHO chunks identically.
- **Runner script** (`run_qdrant_ingestion.py`) — production entry point loading all three text sources plus WHO images and links, uploading everything, and verifying final counts server-side. Supports `--reset` for an explicit, logged, destructive collection rebuild; defaults to safe/non-destructive.
- **Two collections**: `medrag_text` (1536-dim, cosine, all three text sources combined) and `medrag_images` (512-dim, cosine, WHO images only) — separate collections since vector dimensions differ between text and image embeddings.

## Key Design Decisions

1. **Separate collections per modality, not one combined collection.** Qdrant collections are single-dimension; text (1536-dim) and image (512-dim) vectors can't coexist in one collection. This also keeps search logic clean — text queries and image queries never need to filter out the wrong modality.
2. **All three text sources uploaded into one shared `medrag_text` collection**, rather than deferring PubMed/OpenFDA to a later phase. The point-building logic is identical regardless of source (same `Chunk` model, same payload shape, `linked_images` simply empty for non-WHO chunks), so splitting this into multiple phases would have added process overhead without genuine scope control. A partially-populated `medrag_text` would also have been a trap for Phase 9+ retrieval work, which needs to assume full-corpus behavior from the start.
3. **Production collection creation is non-destructive by default.** The notebook's collection reset (drop-then-recreate) was a one-time fix for stale test data from an earlier, buggy notebook run. `ensure_collections()` in production only creates a collection if it doesn't already exist; the destructive drop-and-recreate path (`reset_collections()`) is opt-in only, via an explicit `--reset` flag, and logged loudly since it discards existing data. A normal re-run of the ingestion script should never silently wipe a real deployment.
4. **Deterministic point IDs throughout**, extending Phase 6's `Chunk.make_point_id()` pattern: WHO images get a UUID5 generated from their filename (`generate_image_point_id()`), so re-running ingestion never creates duplicate points for the same image, and any chunk's `linked_images` payload can reference an image's point_id without a separate lookup or ID-matching step.
5. **Bidirectional link maps built once, not looked up per-query.** Phase 7's link records only store one direction per row (chunk_id paired with image_filename). `build_link_maps()` builds both `chunk_to_images` and `image_to_chunks` dictionaries in a single pass, so retrieval logic in later phases gets O(1) lookups in both directions rather than scanning the full link list per query.
6. **Mention-level link deduplication applied before point-building, not after.** Phase 7's linker records one row per figure *mention*, not per unique (chunk, image) pair — a chunk mentioning the same figure twice produces two identical rows. `dedupe_links()` collapses these by `(chunk_id, image_filename)` before any payload is built, so no duplicate entries reach the uploaded `linked_images`/`linked_chunks` payload fields.
7. **Failed lookups are counted and logged, not silently dropped or raised.** `upload_source_chunks()` skips (and counts) any embedding row whose `chunk_id` has no matching entry in the loaded chunk lookup, rather than crashing the whole run. This can legitimately happen if embeddings and chunk files ever drift out of sync, and should be visible in the log rather than hidden.

## Results

- **22,696 total text points uploaded to `medrag_text`**: WHO 4,804 + PubMed 4,725 + OpenFDA 13,167 — matching Phase 6's final confirmed totals exactly.
- **76 image points uploaded to `medrag_images`** — matching Phase 7's final unique image count exactly.
- **48 of 4,804 WHO chunks carry at least one linked image; 22 of 76 images carry at least one linked chunk** — consistent with Phase 7's final validated linking numbers (55 links after ToC-chunk exclusion, 50 after mention-level dedup).
- Server-side `client.count(exact=True)` verification confirms both collections hold exactly the expected point counts — not just what the upload loop's own tally claimed.
- Production script (`run_qdrant_ingestion.py`) re-run confirmed to reproduce the notebook's exact result: 22,696 / 76, matching precisely.

## Challenges & Solutions

- **An earlier notebook run had already upserted test data built from stale, pre-fix linking data.** Before Phase 7's List-of-Figures/ToC-chunk bug fix was applied to disk, an initial Phase 8 test run loaded the old 61-link file (including the bogus ToC-chunk links) and upserted a small test batch reflecting that bug into both collections. Caught by noticing a search result reporting `linked_images=6` for a chunk already known to be the ToC bug from Phase 7's writeup. Resolved by restarting the notebook cleanly: re-ran Phase 7's linker to regenerate the corrected 55-link file, dropped and recreated both collections to purge the stale test points, and re-verified the corrected data end-to-end (search results, payload round-trips, and a final duplicate-pair assertion) before any full-scale upload.
- **Kernel working-directory fragility caused an import failure** (`ModuleNotFoundError: No module named 'run_chunking'`) when the notebook was launched with a working directory far from the project (`C:\Users\DELL\Desktop`, not the project folder). Fixed with a `find_project_root()` helper that walks upward from the kernel's actual `cwd` searching for a `backend/` folder, anchoring all `sys.path` entries to the discovered root rather than a hardcoded relative path — makes the notebook robust to however Jupyter happens to be launched.
- **Qdrant connection refused on first attempt** (`WinError 10061`) — the Docker container running Qdrant had not been started for this session. Resolved by starting the container via Docker Desktop and confirming reachability with `client.get_collections()` before proceeding.

## Files Created

- `backend/src/medrag/embeddings/qdrant_client.py` (`get_qdrant_client`, `ensure_collections`, `reset_collections`, `generate_image_point_id`)
- `backend/src/medrag/embeddings/qdrant_ingestion.py` (`dedupe_links`, `build_link_maps`, `build_text_point`, `build_image_point`, `upload_points`, `upload_source_chunks`, `upload_images`)
- `backend/scripts/run_qdrant_ingestion.py` (supports `--reset` for explicit destructive rebuild)
- `notebooks/phase08_qdrant_setup.ipynb`
- Qdrant collections `medrag_text` (22,696 points) and `medrag_images` (76 points), persisted in the running Qdrant Docker container