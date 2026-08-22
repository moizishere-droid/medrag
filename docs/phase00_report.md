# MedRAG — Multilingual Multimodal Medical Knowledge RAG System

### Phase 0: Project Documentation & Architecture (Updated Through Phase 7)

---

## 1. Problem Statement

Medical knowledge — research papers, clinical guidelines, drug databases — is overwhelmingly published in English. PubMed, WHO guidelines, and drug regulatory data are almost entirely English-first resources. This creates a real barrier:

- Non-English-speaking patients cannot understand medical literature relevant to their own care.
- Doctors and healthcare workers in non-English-speaking regions face friction accessing the latest medical evidence quickly.
- Medical information also isn't purely text — diagrams, X-rays, and dosage tables carry critical meaning that plain-text search tools ignore entirely.

There is no simple, free, production-grade system that lets a person ask a medical question in their own language and get an accurate, cited answer synthesized from real English medical literature — across text, images, and tables.

## 2. Solution

**MedRAG** is a Retrieval-Augmented Generation (RAG) system that:

- Ingests medical literature from free, public sources (PubMed, WHO, OpenFDA).
- Processes **text, images, and tables** — not just plain text.
- Retrieves relevant content using **hybrid search** (keyword + semantic), refined with reranking.
- Builds a **medical knowledge graph** (drug–disease relationships) for structured reasoning alongside retrieval.
- Generates answers **in the user's own language** — even though source material stays English. Translation happens at the generation step, not the ingestion step.
- Cites its sources and is evaluated against RAGAS metrics for answer faithfulness and relevance.

## 3. Key Design Decision: Multilingual Output, Not Multilingual Ingestion

MedRAG ingests **English-only sources** and lets the LLM translate/generate the final answer in the user's query language, rather than ingesting documents in six languages. This keeps the ingestion pipeline simple and maintainable while still delivering the value a non-English speaker needs.

**Design principle locked during ingestion (Phases 2-4):** each source answers a genuinely different question, and gaps in one source are stated honestly rather than hidden or forced:
- **PubMed** → "What does the research show?"
- **OpenFDA** → "What does the FDA-approved drug label say?"
- **WHO** → "What are the official global health recommendations?"

A topic missing coverage from one source (e.g., no WHO guidance, or few OpenFDA-labeled drugs) still has full coverage from the other two — the system is designed to say so honestly rather than fabricate or blend sources silently.

## 4. Advantages / What Makes This Project Stand Out

- **True multimodality** — text, image, and table retrieval, not just text.
- **Structured + unstructured reasoning combined** — vector search *and* a knowledge graph.
- **Real-world relevance** — addresses an actual healthcare access gap.
- **Production-oriented engineering, not notebook-only** — every phase built cell-by-cell in a notebook first, then lifted into tested, documented production code, with real bugs found and fixed through deliberate end-to-end review (not just "it ran once").
- **Quantifiable evaluation** — RAGAS gives objective faithfulness/relevance scores (planned, Phase 18).
- **Free, legally clean data sources** — PubMed, OpenFDA, and WHO via their public APIs/repositories.
- **Honest scope, not inflated claims** — 12 of 36 topics have no dedicated WHO guideline (confirmed genuine, not a search-bias gap); OpenFDA drug counts vary honestly by topic based on real FDA-label availability. Both are documented as accurate reflections of real-world data, not hidden.

## 5. Technology Stack (Confirmed as Actually Used, Through Phase 7)

| Layer | Technology | Why |
|---|---|---|
| LLM (planned) | GPT-4-turbo (OpenAI) | Multilingual generation + medical reasoning |
| Text Embeddings | `text-embedding-3-small` (OpenAI) | Cost-efficient (~$0.13 for the full corpus), strong retrieval performance |
| Image Embeddings | CLIP `ViT-B-32` (OpenAI pretrained, via `open-clip-torch`) | Standard vision-text embedding model; runs locally on CPU at this scale |
| Vector DB (planned) | Qdrant | Open-source, fast, filterable, Docker-deployable |
| Graph DB (planned) | Neo4j | Native fit for drug-disease relationship modeling |
| Chat History (planned) | PostgreSQL | Relational storage for conversational memory |
| Sentence Splitting | spaCy (rule-based `sentencizer`, not the statistical parser) + custom medical-abbreviation fix | Statistical parser refuses manual sentence-boundary overrides; rule-based sentencizer allows the abbreviation correction needed for medical text (Fig., e.g., vs., mg., etc.) |
| PDF Text/Table Extraction | `pdfplumber` | Table-aware extraction; `pypdf` was tried first and found to badly garble tables |
| PDF Image Extraction | `PyMuPDF` (`fitz`) | Extracts embedded images; also used to rasterize full pages for vector-drawn figures/diagrams that have no embedded image object |
| Sparse Retrieval (planned) | BM25 | Exact keyword matching for drug names/dosages |
| Reranking (planned) | Cross-Encoder | Refines top hybrid-retrieval candidates |
| Backend (planned) | FastAPI | API framework |
| Frontend (planned) | Streamlit | Demo UI |
| Evaluation (planned) | RAGAS | Faithfulness/relevance metrics |
| Testing | pytest | Automated tests |
| Deployment (planned) | Docker + Railway | Containerized, reproducible deployment |

## 6. System Architecture (Actual Flow, Through Phase 7)

```
                    RAW DATA SOURCES
        PubMed API | OpenFDA API | WHO IRIS (PDFs)
                         │
                         ▼
                 INGESTION LAYER
   PubMed: ESearch/EFetch, XML parsing (Phase 2)
   OpenFDA: exact-phrase search, JSON parsing (Phase 3)
   WHO: handle→item→bundle→bitstream URL resolution,
        unified pdfplumber/PyMuPDF extraction (Phase 4)
                         │
                         ▼
              CROSS-TOPIC DEDUPLICATION
   Same content (WHO shared docs, OpenFDA drugs used for
   multiple conditions, PubMed papers relevant to several
   topics) is chunked/embedded ONCE, tagged with every
   topic it belongs to (Chunk.topics: List[str])
                         │
                         ▼
                PROCESSING LAYER (Phase 6)
   Source-aware chunking: PubMed (minimal splitting),
   OpenFDA (field-based), WHO (sentence-based via spaCy;
   tables kept atomic or row-split if oversized)
   Contextual prefixing applied to every chunk's embedded
   text (title/field/table context) for standalone meaning
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
      TEXT EMBEDDINGS         IMAGE EMBEDDINGS
   OpenAI text-embedding-    CLIP ViT-B-32 (Phase 7)
   3-small (Phase 6)         WHO images only, deduplicated
   Deduplicated by point_id  with cover-page exclusion rule
              │                     │
              └──────────┬──────────┘
                         ▼
                 STORAGE LAYER (planned)
        Qdrant (vectors) | Neo4j (knowledge graph)
              | Postgres (chat memory)
                         ▼
                RETRIEVAL LAYER (planned)
     BM25 + Vector Search → RRF Fusion → Cross-Encoder
                         ▼
                GENERATION LAYER (planned)
    GPT-4-turbo + retrieved context → cited answer in
              user's language
                         ▼
                 SERVING LAYER (planned)
              FastAPI (API) → Streamlit (UI)
```

## 7. Data Schema (As Actually Implemented)

| Stage          | Shape                                                                                                                  |
|----------------|------------------------------------------------------------------------------------------------------------------------|
| Raw (PubMed)   | `Article{pmid, title, abstract, authors, journal, pub_date, language, topic, source, url}`                             |
| Raw (OpenFDA)  | `DrugRecord{brand_name, generic_name, drug_class, indications_and_usage, dosage_and_administration, contraindications, warnings_and_cautions, adverse_reactions, drug_interactions, mechanism_of_action, topic, source}`                                         |
| Raw (WHO)      | `Guideline{title, topic, clean_text, raw_text, num_pages, num_tables, num_images, source_url, source}` + `WhoTable{topic, page_number, table_data}` + `WhoImage{topic, page_number, image_index, filename, width, height, image_type}`                              |
| Chunked        | `Chunk{chunk_id, point_id, text, raw_text, source, topics: List[str], source_id, chunk_index, chunk_type, metadata}`   |
| Text Embedded  | `.npy` array (float32) + JSONL index `{point_id, chunk_id, source, topics, source_id, chunk_type}`                     |
| Image Embedded | `.npy` array (float32, 512-dim) + JSONL index `{filename, topics, page_number, image_type}`                            |

## 8. Actual Data Scope (Confirmed Through Phase 7, Supersedes Earlier Estimates)

- **36 project topics** (not the originally-discussed 32 — some were split further during PubMed ingestion), spanning chronic/metabolic, respiratory, cardiovascular, infectious, mental health, gastrointestinal, musculoskeletal, endocrine, neurological, renal, common cancers, and maternal/child health conditions.
- **PubMed:** 4,159 unique articles → 4,725 chunks (after deduplicating ~10% genuine cross-topic overlap, e.g. comorbidity papers).
- **OpenFDA:** 467 unique drugs → 13,167 chunks (24 of 36 topics reach the 25-drug target; several genuinely have fewer real FDA-labeled drugs, e.g. malnutrition, typhoid, dengue fever).
- **WHO:** 24 of 36 topics have a real WHO guideline (17 unique documents, several shared across related topics); 4,804 unique chunks including row-split table pieces for oversized tables; 76 unique images.
- **12 topics have no dedicated WHO guideline** (osteoarthritis, rheumatoid arthritis, osteoporosis, chronic kidney disease, lung cancer, peptic ulcer disease, irritable bowel syndrome, arrhythmia, hypothyroidism, hyperthyroidism, migraine, Parkinson's disease) — confirmed genuine via broad, non-IRIS-restricted search, not a search-bias artifact.
- **Total unique chunks across all sources: 22,688.** Total unique text embeddings: 22,696 (WHO count includes a small number of extra pieces from oversized-table row-splitting). Total unique image embeddings: 76.

## 9. Methodology (Followed for Every Phase, Confirmed in Practice)

1. **Teach** — Concepts explained before any code.
2. **Notebook** — Build/experiment cell by cell; run and verify each step on real data before scaling.
3. **Src/ Files** — Clean production code based exactly on validated notebook logic — no new untested logic introduced during the lift.
4. **Phase Report** — What was built, key decisions, results, challenges, next phase preview.
5. **Git Commit** — Committed after each completed phase.
6. **Final review before moving on** — In practice, this repeatedly caught real issues (cross-topic duplication across all three sources, OpenFDA false-positive search matching, oversized table chunks exceeding the embedding model's token limit) that a single successful run alone would not have surfaced. This deliberate re-checking step is now considered part of the standard methodology, not optional polish.

## 10. Known Limitations (Documented Honestly, Not Hidden)

- **WHO's IRIS repository resolution is unofficial/reverse-engineered** (its JS-based frontend broke old direct download links) — stable for now, but a future WHO platform change could require re-fixing the resolver.
- **CLIP's usefulness on this project's images is real but modest** — it captures general visual layout/style, not dense document text; same-document image similarity (0.73) is meaningfully but not dramatically higher than cross-document similarity (0.55).
- **Image-to-text-chunk linking is designed but not yet implemented** (planned: match each image to its nearby caption text in a chunk's `raw_text`).
- **OpenFDA/PubMed/WHO cross-topic content sharing was fixed via deduplication + a `topics` list**, not by preventing the overlap from existing in raw ingested data (which is fine, and arguably more honest, since the overlap in raw PubMed/OpenFDA data reflects genuine real-world topic relevance).

## 11. Project Structure (Confirmed Through Phase 7)

```
medrag/
├── .github/workflows/
├── backend/
│   ├── src/medrag/
│   │   ├── ingestion/       ← Phases 2-4 (PubMed, OpenFDA, WHO)
│   │   ├── processing/      ← Phase 6 (chunking)
│   │   ├── embeddings/      ← Phases 6-7 (text + image embeddings)
│   │   ├── retrieval/       ← planned
│   │   ├── graph/           ← planned
│   │   ├── generation/      ← planned
│   │   ├── memory/          ← planned
│   │   └── evaluation/      ← planned
│   ├── config/settings.py
│   └── scripts/             ← run_ingestion.py, run_openfda_ingestion.py,
│                               run_who_ingestion.py, run_chunking.py,
│                               run_embeddings.py, run_image_embeddings.py
├── frontend/                 ← planned
├── data/
│   ├── raw/{pubmed,openfda,who}/
│   ├── tables/who/
│   ├── images/who/
│   └── processed/{chunks,embeddings}/
├── docs/                       ← phase00-07 reports
├── notebooks/                   ← phase02-07 notebooks
├── tests/                        ← planned
├── pyproject.toml
├── docker-compose.yml
└── README.md
```