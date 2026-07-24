# MedRAG — Multilingual Multimodal Medical Knowledge RAG System
### Phase 0: Project Documentation & Architecture

---

## 1. Problem Statement

Medical knowledge, including research papers, clinical guidelines, and drug reference databases, is predominantly published in English. This creates a significant accessibility barrier for healthcare professionals and patients who are more comfortable using other languages.

In addition, medical information is inherently multimodal. Clinical documents often contain diagnostic images, charts, dosage tables, and figures that traditional text-only search systems cannot effectively retrieve or interpret.

Although several AI-powered medical search tools exist, many are protected by a patent, primarily English-focused, or provide limited multilingual and multimodal evidence retrieval. There is a need for an open, citation-backed system that enables users to ask medical questions in their native language while retrieving and synthesizing evidence from English medical literature across multiple data modalities.

## 2. Solution

**MedRAG** is a Retrieval-Augmented Generation (RAG) system that:

- Ingests (receiving raw data) medical literature from free, public sources (PubMed, WHO, OpenFDA, Medical Wikipedia, user uploads).
- Processes **text, images, and tables** — not just plain text.
- Retrieves relevant content using **hybrid search** (keyword + semantic), refined with reranking.
- Builds a **medical knowledge graph** (drug–disease relationships) for structured reasoning alongside retrieval.
- Generates answers in the user's preferred language while retrieving evidence from English medical literature. Translation occurs during the generation step, not during data ingestion.
- Cites its sources and is evaluated against RAGAS metrics for answer faithfulness and relevance.


## 3. Advantages / What Makes This Project Stand Out

- **True multimodality** — most RAG portfolio projects are text-only; this one retrieves across text, images, and tables.
- **Structured + unstructured reasoning combined** — vector search *and* a knowledge graph, not just one retrieval strategy.
- **Real-world relevance** — addresses an actual healthcare access gap, not a toy dataset.
- **Production-oriented, not notebook-only** — FastAPI + Docker + CI/CD + evaluation metrics (RAGAS), showing engineering maturity beyond a single script.
- **Quantifiable evaluation** — RAGAS gives objective faithfulness/relevance scores rather than "it looks right" judgment.
- **Free, legally clean data sources** — no scraping ToS violations; everything comes from open APIs (PubMed, OpenFDA) and public guidelines (WHO).

## 4. Technology Stack

| Layer               | Technology                         | Why                                                         |
|---------------------|------------------------------------|-------------------------------------------------------------|
| LLM                 | GPT-4-turbo (OpenAI)               | Strong multilingual generation + medical reasoning          |
| Text Embeddings     | text-embedding-3-small (1536 dims) | Cost-efficient, strong retrieval performance                |
| Image Embeddings    | CLIP (open-clip-torch)             | Standard, well-supported vision-text embedding model        |
| Vector DB           | Qdrant                             | Open-source, fast, supports filtering, easy Docker deploy   |
| Graph DB            | Neo4j                              | Native fit for drug-disease relationship modeling           |
| Chat History        | PostgreSQL                         | Reliable relational storage for conversational memory       |
| NER                 | SpaCy + scispaCy                   | Domain-tuned biomedical entity recognition                  |
| Sparse Retrieval    | BM25                               | Exact keyword matching (critical for drug names/dosages)    |
| Reranking           | Cross-Encoder                      | Refines top candidates from hybrid retrieval for precision  |
| Backend             | FastAPI                            | Fast, typed, async-friendly Python API framework            |
| Frontend            | Streamlit                          | Quick, clean UI for demoing an ML/RAG system                |
| Evaluation          | RAGAS                              | Standard RAG evaluation framework (faithfulness, relevance) |
| Experiment Tracking | Weights & Biases                   | Tracks embedding/retrieval/eval experiments                 |
| Testing             | pytest                             | Automated test suite for reliability                        |
| CI/CD               | GitHub Actions                     | Automated testing/build on every commit                     |
| Deployment          | Docker + Railway                   | Containerized, reproducible, publicly deployed demo         |

## 5. System Architecture

```
                         ┌─────────────────────────────┐
                         │      RAW DATA SOURCES       │
                         │ PubMed | WHO | OpenFDA |    │
                         │ Medical Wikipedia | Uploads │
                         └───────────────┬─────────────┘
                                         ▼
                         ┌─────────────────────────────┐
                         │      INGESTION LAYER        │
                         │  (text, images, tables)     │
                         └───────────────┬─────────────┘
                                         ▼
                         ┌─────────────────────────────┐
                         │      PROCESSING LAYER       │
                         │ Medical-aware chunking,     │
                         │ image/table extraction      │
                         └───────────────┬─────────────┘
                                         ▼
                  ┌──────────────────────┴──────────────────────┐
                  ▼                                              ▼
     ┌─────────────────────────┐                    ┌─────────────────────────┐
     │   TEXT EMBEDDINGS       │                    │   IMAGE EMBEDDINGS      │
     │ (OpenAI text-embed-3)   │                    │        (CLIP)           │
     └────────────┬────────────┘                    └────────────┬────────────┘
                  └──────────────────────┬───────────────────────┘
                                         ▼
                         ┌─────────────────────────────┐
                         │        STORAGE LAYER        │
                         │ Qdrant (vectors) | Neo4j    │
                         │ (knowledge graph) | Postgres│
                         │ (chat memory)               │
                         └───────────────┬─────────────┘
                                         ▼
                         ┌─────────────────────────────┐
                         │      RETRIEVAL LAYER        │
                         │ BM25 + Vector Search →      │
                         │ RRF Fusion → Cross-Encoder  │
                         │ Reranking                   │
                         └───────────────┬─────────────┘
                                         ▼
                         ┌─────────────────────────────┐
                         │      GENERATION LAYER       │
                         │ GPT-4-turbo + retrieved     │
                         │ context → cited answer in   │
                         │ user's language             │
                         └───────────────┬─────────────┘
                                         ▼
                         ┌─────────────────────────────┐
                         │       SERVING LAYER         │
                         │  FastAPI (API) → Streamlit  │
                         │          (UI)               │
                         └─────────────────────────────┘
```

## 6. Data Schema (How a Document Evolves Through the Pipeline)

| Stage            | Shape                                                           |
|------------------|-----------------------------------------------------------------|
| Raw              | `{source, title, full_text, images[], tables[], language, url}` |
| Chunked          | `{doc_id, chunk_id, text, section, metadata}`                   |
| Embedded         | `{chunk_id, vector, model_name}`                                |
| Retrieved        | `{chunk_id, score, rerank_score}`                               |
| Generated Answer | `{query, answer, citations[], language}`                        |

## 7. Complete Phase Plan

| Phase | Description                          |
|-------|--------------------------------------|
| 0     | Project Documentation & Architecture |
| 1     | Environment Setup                    |
| 2     | PubMed Data Ingestion (text)         |
| 3     | WHO Guidelines + OpenFDA Ingestion   |
| 4     | Image Extraction (medical diagrams)  |
| 5     | Table Extraction (drug tables)       |
| 6     | Text Chunking (medical-aware)        |
| 7     | Text Embeddings (OpenAI)             |
| 8     | Image Embeddings (CLIP)              |
| 9     | Qdrant Vector Store                  |
| 10    | BM25 Sparse Retrieval                |
| 11    | Hybrid Retrieval (RRF)               |
| 12    | Cross-Encoder Reranking              |
| 13    | Medical NER (SpaCy + scispaCy)       |
| 14    | Neo4j Knowledge Graph                |
| 15    | LLM Answer Generation (GPT-4-turbo)  |
| 16    | Citation System                      |
| 17    | Chat Memory (PostgreSQL)             |
| 18    | RAGAS Evaluation                     |
| 19    | FastAPI Backend                      |
| 20    | Streamlit Frontend                   |
| 21    | Testing Suite (pytest)               |
| 22    | CI/CD (GitHub Actions)               |
| 23    | Docker Deployment                    |
| 24    | Railway Production Deployment        |

## 8. Project Structure

```
medrag/
├── .github/workflows/     ← CI/CD
├── backend/
│   ├── src/
|       ├──medrag.egg-info
|       ├──medrag
│            ├── ingestion/     ← Phases 2-5
│            ├── processing/    ← Phase 6
│            ├── embeddings/    ← Phases 7-8
│            ├── retrieval/     ← Phases 9-12
│            ├── graph/         ← Phases 13-14
│            ├── generation/    ← Phases 15-16
│            ├── memory/        ← Phase 17
│            └── evaluation/    ← Phase 18
│   ├── api/                    ← Phase 19
│   ├── config/
│   └── scripts/
├── frontend/                   ← Phase 20
├── data/
│   ├── raw/                    ← papers, PDFs
│   ├── images/                 ← medical diagrams
│   ├── tables/                 ← drug tables
│   └── processed/              ← chunks
├── docs/
├── notebooks/
├── tests/                  ← Phase 21
├── pyproject.toml          ← medrag package
├── install.bat
├── docker-compose.yml
├── .env.example
├── .env
└── README.md
└── .gitignore
└── python-version
```