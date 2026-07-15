# MedRAG — Multilingual Multimodal Medical Knowledge RAG System
### Phase 0: Project Documentation & Architecture

---

## 1. Problem Statement

Medical knowledge — research papers, clinical guidelines, drug databases — is overwhelmingly published in English. PubMed, WHO guidelines, and drug regulatory data are almost entirely English-first resources. This creates a real barrier:

- Non-English-speaking patients cannot understand medical literature relevant to their own care.
- Doctors and healthcare workers in non-English-speaking regions face friction accessing the latest medical evidence quickly.
- Medical information also isn't purely text — diagrams, X-rays, and dosage tables carry critical meaning that plain-text search tools ignore entirely.

There is no simple, free, production-grade system that lets a person ask a medical question in their own language and get an accurate, cited answer synthesized from real English medical literature — across text, images, and tables.

## 2. Solution

**MedRAG** is a Retrieval-Augmented Generation (RAG) system that:

- Ingests medical literature from free, public sources (PubMed, WHO, OpenFDA, Medical Wikipedia, user uploads).
- Processes **text, images, and tables** — not just plain text.
- Retrieves relevant content using **hybrid search** (keyword + semantic), refined with reranking.
- Builds a **medical knowledge graph** (drug–disease relationships) for structured reasoning alongside retrieval.
- Generates answers **in the user's own language** (English, Arabic, French, German, Spanish, Urdu) — even though source material stays English. Translation happens at the generation step, not the ingestion step.
- Cites its sources and is evaluated against RAGAS metrics for answer faithfulness and relevance.

## 3. Key Design Decision: Multilingual Output, Not Multilingual Ingestion

An early and important scoping decision: rather than ingesting documents in six different languages (which would multiply pipeline complexity — six sets of chunking rules, six embedding behaviors, six language-detection edge cases — for source material that is genuinely English-dominated anyway), MedRAG ingests **English-only sources** and lets the LLM translate/generate the final answer in the user's query language.

This keeps the ingestion pipeline simple and maintainable while still delivering the actual value a non-English speaker needs: an answer they can read, in their own language, grounded in real medical literature.

## 4. Advantages / What Makes This Project Stand Out

- **True multimodality** — most RAG portfolio projects are text-only; this one retrieves across text, images, and tables.
- **Structured + unstructured reasoning combined** — vector search *and* a knowledge graph, not just one retrieval strategy.
- **Real-world relevance** — addresses an actual healthcare access gap, not a toy dataset.
- **Production-oriented, not notebook-only** — FastAPI + Docker + CI/CD + evaluation metrics (RAGAS), showing engineering maturity beyond a single script.
- **Quantifiable evaluation** — RAGAS gives objective faithfulness/relevance scores rather than "it looks right" judgment.
- **Free, legally clean data sources** — no scraping ToS violations; everything comes from open APIs (PubMed, OpenFDA) and public guidelines (WHO).

## 5. Technology Stack

| Layer | Technology | Why |
|---|---|---|
| LLM | GPT-4-turbo (OpenAI) | Strong multilingual generation + medical reasoning |
| Text Embeddings | text-embedding-3-small (1536 dims) | Cost-efficient, strong retrieval performance |
| Image Embeddings | CLIP (open-clip-torch) | Standard, well-supported vision-text embedding model |
| Vector DB | Qdrant | Open-source, fast, supports filtering, easy Docker deploy |
| Graph DB | Neo4j | Native fit for drug-disease relationship modeling |
| Chat History | PostgreSQL | Reliable relational storage for conversational memory |
| NER | SpaCy + scispaCy | Domain-tuned biomedical entity recognition |
| Sparse Retrieval | BM25 | Exact keyword matching (critical for drug names/dosages) |
| Reranking | Cross-Encoder | Refines top candidates from hybrid retrieval for precision |
| Backend | FastAPI | Fast, typed, async-friendly Python API framework |
| Frontend | Streamlit | Quick, clean UI for demoing an ML/RAG system |
| Evaluation | RAGAS | Standard RAG evaluation framework (faithfulness, relevance) |
| Experiment Tracking | Weights & Biases | Tracks embedding/retrieval/eval experiments |
| Testing | pytest | Automated test suite for reliability |
| CI/CD | GitHub Actions | Automated testing/build on every commit |
| Deployment | Docker + Railway | Containerized, reproducible, publicly deployed demo |

## 6. System Architecture

```
                         ┌─────────────────────────────┐
                         │      RAW DATA SOURCES        │
                         │ PubMed | WHO | OpenFDA |      │
                         │ Medical Wikipedia | Uploads   │
                         └───────────────┬───────────────┘
                                         ▼
                         ┌─────────────────────────────┐
                         │      INGESTION LAYER         │
                         │  (text, images, tables)       │
                         └───────────────┬───────────────┘
                                         ▼
                         ┌─────────────────────────────┐
                         │      PROCESSING LAYER        │
                         │ Medical-aware chunking,       │
                         │ image/table extraction        │
                         └───────────────┬───────────────┘
                                         ▼
                  ┌──────────────────────┴──────────────────────┐
                  ▼                                              ▼
     ┌─────────────────────────┐                    ┌─────────────────────────┐
     │   TEXT EMBEDDINGS        │                    │   IMAGE EMBEDDINGS       │
     │ (OpenAI text-embed-3)    │                    │        (CLIP)            │
     └────────────┬─────────────┘                    └────────────┬─────────────┘
                  └──────────────────────┬──────────────────────┘
                                         ▼
                         ┌─────────────────────────────┐
                         │        STORAGE LAYER         │
                         │ Qdrant (vectors) | Neo4j      │
                         │ (knowledge graph) | Postgres   │
                         │ (chat memory)                  │
                         └───────────────┬───────────────┘
                                         ▼
                         ┌─────────────────────────────┐
                         │      RETRIEVAL LAYER         │
                         │ BM25 + Vector Search →        │
                         │ RRF Fusion → Cross-Encoder     │
                         │ Reranking                      │
                         └───────────────┬───────────────┘
                                         ▼
                         ┌─────────────────────────────┐
                         │      GENERATION LAYER        │
                         │ GPT-4-turbo + retrieved       │
                         │ context → cited answer in      │
                         │ user's language                 │
                         └───────────────┬───────────────┘
                                         ▼
                         ┌─────────────────────────────┐
                         │       SERVING LAYER          │
                         │  FastAPI (API) → Streamlit    │
                         │          (UI)                  │
                         └─────────────────────────────┘
```

## 7. Data Schema (How a Document Evolves Through the Pipeline)

| Stage | Shape |
|---|---|
| Raw | `{source, title, full_text, images[], tables[], language, url}` |
| Chunked | `{doc_id, chunk_id, text, section, metadata}` |
| Embedded | `{chunk_id, vector, model_name}` |
| Retrieved | `{chunk_id, score, rerank_score}` |
| Generated Answer | `{query, answer, citations[], language}` |

## 8. Complete Phase Plan

| Phase | Description |
|---|---|
| 0 | Project Documentation & Architecture |
| 1 | Environment Setup |
| 2 | PubMed Data Ingestion (text) |
| 3 | WHO Guidelines + OpenFDA Ingestion |
| 4 | Image Extraction (medical diagrams) |
| 5 | Table Extraction (drug tables) |
| 6 | Text Chunking (medical-aware) |
| 7 | Text Embeddings (OpenAI) |
| 8 | Image Embeddings (CLIP) |
| 9 | Qdrant Vector Store |
| 10 | BM25 Sparse Retrieval |
| 11 | Hybrid Retrieval (RRF) |
| 12 | Cross-Encoder Reranking |
| 13 | Medical NER (SpaCy + scispaCy) |
| 14 | Neo4j Knowledge Graph |
| 15 | LLM Answer Generation (GPT-4-turbo) |
| 16 | Citation System |
| 17 | Chat Memory (PostgreSQL) |
| 18 | RAGAS Evaluation |
| 19 | FastAPI Backend |
| 20 | Streamlit Frontend |
| 21 | Testing Suite (pytest) |
| 22 | CI/CD (GitHub Actions) |
| 23 | Docker Deployment |
| 24 | Railway Production Deployment |

## 9. Project Structure

```
medrag/
├── .github/workflows/     ← CI/CD
├── backend/
│   ├── src/
│   │   ├── ingestion/     ← Phases 2-5
│   │   ├── processing/    ← Phase 6
│   │   ├── embeddings/    ← Phases 7-8
│   │   ├── retrieval/     ← Phases 9-12
│   │   ├── graph/         ← Phases 13-14
│   │   ├── generation/    ← Phases 15-16
│   │   ├── memory/        ← Phase 17
│   │   └── evaluation/    ← Phase 18
│   ├── api/               ← Phase 19
│   ├── config/
│   │   └── settings.py
│   └── scripts/
│       ├── run_ingestion.py
│       ├── run_embeddings.py
│       └── run_evaluation.py
├── frontend/
│   └── app.py             ← Phase 20
├── data/
│   ├── raw/                ← papers, PDFs
│   ├── images/             ← medical diagrams
│   ├── tables/              ← drug tables
│   └── processed/           ← chunks
├── docs/
│   ├── phase00_report.md
│   └── ...
├── notebooks/
│   └── ...
├── tests/                  ← Phase 21
├── pyproject.toml          ← medrag package
├── install.bat
├── docker-compose.yml
├── .env.example
└── README.md
```

## 10. Methodology (Followed for Every Subsequent Phase)

1. **Teach** — Concepts explained before any code.
2. **Notebook** — Build/experiment cell by cell; run and verify each step.
3. **Src/ Files** — Clean production code based exactly on validated notebook logic.
4. **Phase Report** — What was built, key decisions, results, challenges, next phase preview.
5. **Git Commit** — Committed after each completed phase.

---

*End of Phase 0 Documentation.*
