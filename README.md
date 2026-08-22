# MedRAG

### Multilingual Multimodal Medical Knowledge RAG System

MedRAG is a medical Retrieval-Augmented Generation system designed to retrieve knowledge from research papers, drug labels, and clinical guidelines, including **text, tables, and images**.

The project is being built as a production-oriented AI/ML system with multilingual and multimodal retrieval.

> **Current status:** The ingestion, document processing, chunking, text embedding, and image embedding pipeline is implemented. The next phase is Qdrant-based retrieval.

---

## Architecture

```text
PubMed ──────┐
OpenFDA ─────┼──→ Ingestion ─→ Processing ─→ Chunking
WHO ─────────┘                              │
                                            ↓
                              ┌─────────────┴─────────────┐
                              │                           │
                         Text Chunks                  Images
                              │                           │
                              ↓                           ↓
                     OpenAI Embeddings               CLIP
                              │                           │
                              └─────────────┬─────────────┘
                                            ↓
                                  Embedding Storage
                                            │
                                            ↓
                                      Qdrant (Next)
                                            │
                                            ↓
                                   Hybrid Retrieval
                                            │
                                            ↓
                                      Reranking
                                            │
                                            ↓
                                    LLM Generation
```

---

## Current Progress

| Component                        | Status |
| -------------------------------- | ------ |
| Project setup                    | ✅      |
| PubMed ingestion                 | ✅      |
| OpenFDA ingestion                | ✅      |
| WHO PDF processing               | ✅      |
| WHO table extraction             | ✅      |
| WHO image extraction             | ✅      |
| Vector figure/page rasterization | ✅      |
| Source-aware chunking            | ✅      |
| Cross-topic deduplication        | ✅      |
| Text embeddings                  | ✅      |
| Image embeddings                 | ✅      |
| Embedding storage                | ✅      |
| Qdrant retrieval                 | 🔜     |
| BM25 / Hybrid Search             | 🔜     |
| Reranking                        | 🔜     |
| Neo4j Knowledge Graph            | 🔜     |
| LLM Generation                   | 🔜     |
| Citations                        | 🔜     |
| PostgreSQL Memory                | 🔜     |
| RAGAS Evaluation                 | 🔜     |
| FastAPI                          | 🔜     |
| Streamlit UI                     | 🔜     |

---

## Data Sources

### PubMed

Research articles retrieved through NCBI Entrez.

### OpenFDA

Drug-label information including indications, dosage, contraindications, warnings, adverse reactions, and interactions.

### WHO

Clinical guideline PDFs containing:

* Text
* Tables
* Embedded images
* Vector-based figures and diagrams

---

## Processing Pipeline

Different sources use different chunking strategies.

```text
PubMed
→ Sentence-based chunks

OpenFDA
→ Field-based chunks

WHO Text
→ Sentence-based chunks

WHO Tables
→ Table-aware chunks

WHO Images
→ Separate CLIP embedding pipeline
```

Documents shared across multiple topics are processed once and retain all associated topics. This prevents duplicate embeddings and unnecessary storage.

---

## Embeddings

### Text

**Model:** `text-embedding-3-small`

**Dimensions:** 1536

### Images

**Model:** CLIP ViT-B/32

Images are embedded locally and stored separately from text embeddings.

---

## Current Results

| Source                    | Chunks / Embeddings |             Records |
| ------------------------- | ------------------: | ------------------: |
| PubMed                    |        4,725 chunks |      4,159 articles |
| OpenFDA                   |       13,167 chunks |           467 drugs |
| WHO                       |    4,804 embeddings | 24 guideline topics |
| **Total text embeddings** |          **22,696** |                     |

WHO processing also produced approximately **1,204 tables** across the processed guideline documents.

---

## Tech Stack

**Current**

* Python
* Pydantic / pydantic-settings
* Biopython
* pdfplumber
* PyMuPDF
* spaCy
* OpenAI Embeddings
* CLIP
* NumPy
* JSONL

**Planned**

* Qdrant
* BM25
* Cross-Encoder
* Neo4j
* scispaCy
* PostgreSQL
* FastAPI
* Streamlit
* RAGAS

---

## Project Structure

```text
medrag/
├── backend/
│   ├── config/
│   ├── scripts/
│   └── src/
│       └── medrag/
│           ├── ingestion/
│           ├── processing/
│           ├── embeddings/
│           ├── retrieval/
│           ├── graph/
│           └── generation/
│
├── data/
│   ├── raw/
│   ├── images/
│   ├── tables/
│   └── processed/
│
├── docs/
├── notebooks/
├── frontend/
└── tests/
```

---

## Setup

```bash
git clone https://github.com/moizishere-droid/medrag.git
cd medrag
```

Create `.env` from `.env.example` and configure the required API keys.

Install dependencies using the provided setup script:

```bash
install.bat
```

---

## Running the Pipeline

```bash
python backend/scripts/run_ingestion.py
python backend/scripts/run_openfda_ingestion.py
python backend/scripts/run_who_ingestion.py

python backend/scripts/run_chunking.py

python backend/scripts/run_embeddings.py
python backend/scripts/run_image_embeddings.py
```

---

## Documentation

Detailed implementation reports are available in [`docs/`](docs/):

* `phase00_report.md` → Architecture
* `phase01_report.md` → Environment setup
* `phase02_report.md` → PubMed ingestion
* `phase03_report.md` → OpenFDA ingestion
* `phase04_report.md` → WHO processing
* `phase05_report.md` → Chunking
* `phase06_report.md` → Text embeddings

The notebooks contain the experimentation and validation work behind the production code.

---

## Roadmap

```text
Ingestion
   ↓
Processing
   ↓
Chunking
   ↓
Embeddings
   ↓
Qdrant
   ↓
BM25 + Vector Search
   ↓
Hybrid Retrieval
   ↓
Reranking
   ↓
Knowledge Graph
   ↓
LLM Generation + Citations
   ↓
API + UI
   ↓
Evaluation + Deployment
```

---

## License

TBD.

---

**MedRAG**
Multilingual Multimodal Medical Knowledge RAG System
