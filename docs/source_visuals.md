# Source tables and figures in chat

Implemented: 7 October 2026.

## Behavior

Answers can now display **source tables and source figures below the text** when the answer cites WHO evidence carrying those assets. Every panel includes its citation marker and source title. PDF page numbers are displayed one-based; stored extraction page indexes remain zero-based.

Tables preserve extracted cell values, including multiline text, empty cells and literal pipe characters. The interface uses generic column labels and retains original header rows rather than guessing headers. Figures retain the existing extracted image; rasterized pages are labeled as source pages containing the figure. These are source attachments, not images or numerical tables invented by the answer model.

Only cited results from the existing scoped retrieval pipeline are considered. A response includes at most three unique tables and three unique images. Figures must be linked to a cited chunk, match its WHO source topic, appear in the curated image manifest and exist within the curated directory. Duplicate images are omitted.

The feature adds no model calls and does not alter retrieval vectors, ranking or privacy filters. The frontend fetches images with the existing authentication mechanism; bearer tokens are never embedded in browser image URLs. Media failure shows an unavailable-figure message without removing the answer or table. Optional media reads use a five-second timeout without automatic retries.

## API and persistence

Each citation now includes optional `table` and `images` fields:

```json
{
  "marker": 1,
  "chunk_id": "example_who_table",
  "source": "who",
  "title": "Source guideline",
  "table": {"rows": [["Measure", "Finding"], ["A", "B"]], "page_number": 2, "part": null},
  "images": [{"filename": "example.png", "page_number": 4, "figure_number": "1", "image_type": "embedded"}]
}
```

The fields are persisted inside existing PostgreSQL citation JSON and returned with chat history. No database migration is required. Earlier saved messages remain readable but do not acquire visual attachments automatically; new turns receive them.

`GET /media/who/{filename}` serves authenticated, manifest-listed curated PNGs. It rejects unknown filenames and paths outside the WHO image directory, including symlink escapes. It never serves uploaded PDFs, credentials, arbitrary local files or private upload images.

## Existing data and packaging

Existing table chunks resolve against exact saved source rows using source topic, page and table text, so ordinary existing WHO tables do not require reindexing. New table chunks retain structured cells in metadata, including whole row-group parts. Token fragments that cannot safely reconstruct cells are not presented as complete structured tables.

The Docker backend now bundles curated WHO table JSONL and image/manifest files, allowlisted in the build context. The rebuilt image resolved all 100 current WHO images. A read-only check of the existing Qdrant corpus found 48 points with image links and resolved 50 links. These checks did not change the production corpus or user uploads.

## Verification and limits

### Figure mapping correction

The initial display feature exposed a pre-existing ordinal-linking defect: “Figure 2” was mapped to the second extracted bitmap, a cover photograph of tyres. Extraction order is not figure numbering; embedded figure backgrounds can also omit PDF text overlays.

The runtime and link generator now use exact source/figure identifiers from `data/images/who/verified_figures.jsonl`, with captions, page indexes and image SHA-256 checks. The dengue handbook was retrieved from WHO, checked against the saved 124-page source, and its seven explicit figure-caption pages were rendered and visually reviewed. Figure 2 is on PDF page 17 (printed page 7), and its full labeled classification diagram is preserved. These source-page presentation assets do not replace the existing CLIP embedding vectors.

Legacy ordinal filenames are ignored, unverified assets are rejected by the media route, and saved chat citations are revalidated on history reads so the tyre photo cannot reappear through old history. Figure identifiers such as `3.2` are preserved rather than truncated to `3`. Link artifacts were regenerated without changing retrieval vectors or private uploads. Other documents' unverified figures remain hidden until their caption/page mappings are prepared and reviewed; there is no ordinal fallback.

Use `backend/scripts/verify_source_figures.py --pdf <original-pdf> --source-id <exact-canonical-id> --source-url <original-url>` to prepare additional mappings, then visually review them. The command requires a local PDF and makes no network/database calls. Repeated caption identifiers are considered ambiguous and omitted.

- Default suite: **314 passed**; integration suite: **51 passed**.
- After the figure-mapping correction: **318 ordinary tests and 51 integration tests passed**. The existing Qdrant classification chunk resolves to the verified Figure 2 source page without database reindexing.
- Tests cover exact cell preservation, image/source matching, deduplication, missing assets, path restrictions, private-upload exclusion, API authentication, visual JSON persistence and history reload.
- Streamlit AppTest renders a table and source figure, checks page/caption provenance, and verifies graceful unavailable-media behavior.
- Real PostgreSQL integration verifies a completed chat's table survives history reload.
- Backend Docker build and bundled-asset resolution passed. No paid live generation calls were made.

Not every response has visual evidence. The model must cite an eligible chunk; the feature does not independently search the CLIP image collection. Source-link extraction may be imperfect and is not a clinical relevance guarantee. Current private PDF uploads still use text extraction; table/image extraction from uploaded PDFs and image-question input remain outside this implementation. Source extraction does not guarantee the original PDF's visual layout or merged-cell fidelity.

Generation context now lists verified figure captions and PDF pages using the same resolver as the response attachments. The model is instructed to cite the relevant block and acknowledge the attached source figure rather than claim it cannot be displayed. It receives captions rather than image pixels and must not invent unseen visual details. This fixes the gap where a text-only refusal omitted citation markers and consequently prevented an otherwise available figure from reaching the frontend. A regression test checks the context-to-citation-to-image path and excludes private-upload matches. Live model behavior remains unverified without a paid query.

The first generation-context implementation mistakenly searched `backend/data` rather than the repository's `data` folder. Corrected the path and added a regression test using the default catalog and actual bundled dengue assets, without an injected test catalog. This catches the difference between fixture-based success and the real application path.

A live response cited `dengue fever_who_text_26`, whose extracted diagram cells begin with the exact caption heading but omit the figure number. The resolver now also accepts a complete standalone verified caption heading in the same WHO document. Partial headings, keyword/substring matches, ambiguous captions, other documents and private uploads cannot resolve that mapping. A read-only check of the actual Qdrant chunk confirmed it attaches verified Figure 2 and includes the figure in generation context. The affected generation, visual, API and frontend tests passed (47 tests). The user also confirmed that the older tyre-image reply now displays the correct labeled WHO diagram.

Restart both the API and Streamlit after updating. Keep the bundled source assets available in deployment. Ask a new question whose retrieved/cited WHO evidence contains a table or figure; historical text-only responses are unchanged.
