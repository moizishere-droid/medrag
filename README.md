# MedRAG

### Multilingual Multimodal Medical Knowledge RAG System

MedRAG is a medical Retrieval-Augmented Generation system designed to retrieve knowledge from research papers, drug labels, and clinical guidelines, including **text, tables, and images**.

The project is being built as a production-oriented AI/ML system with multilingual and multimodal retrieval.

> **Current status:** Phases 00–21 are complete for local engineering verification. Authentication, upload isolation, failure recovery and testing are implemented. See [Phase 21](docs/phase21_report.md) and [the phase-by-phase audit](docs/project_audit_report.md) for results and limits. Phase 22 is GitHub Actions CI/CD; deployment follows after choosing a platform.

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
                                      Qdrant
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
| Qdrant retrieval                 | ✅     |
| BM25 / Hybrid Search             | ✅     |
| Reranking                        | ✅     |
| Neo4j Knowledge Graph            | ✅     |
| LLM Generation                   | ✅     |
| Citations                        | ✅     |
| PostgreSQL Memory                | ✅     |
| RAGAS Evaluation                 | ✅     |
| FastAPI                          | ✅     |
| Streamlit UI                     | ✅     |

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

**Also implemented**

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

Authentication is required by default. Create an account in the UI, or through
`POST /auth/register`, and use its bearer token for private API routes.
`AUTH_REQUIRED=false` is a local-only development mode; keep authentication
enabled for deployment. Existing unowned sessions remain separate from new
accounts. Uploads are private to the session in which they were indexed.

Install dependencies using the provided setup script:

```bash
install.bat
```

Run the backend with `python -m uvicorn medrag.api.main:app --app-dir backend/src`
and the frontend with `python -m streamlit run frontend/streamlit_app.py`.
Set `MEDRAG_API_URL` for a backend other than `http://localhost:8000`.

Run default tests with `python -m pytest -q`. With the three database services
running, use `python -m pytest -m "not live" -q` for unit and integration tests.
See [Phase 21](docs/phase21_report.md) for isolated-test safeguards and validation
commands. Compose pins the locally verified database builds; development
credentials and open ports require deployment configuration.

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

The Streamlit frontend keeps sign-in across refresh using an HttpOnly API cookie
(24 hours by default, controlled by `AUTH_TOKEN_HOURS`). Sign out revokes the
token and clears the cookie. Use the same hostname for the browser frontend and browser API
(`localhost` on both, or `127.0.0.1` on both). `MEDRAG_API_URL` is the address
reachable by Streamlit; `MEDRAG_BROWSER_API_URL` is the address reachable by the
browser. Local server requests default to `127.0.0.1:8000` to avoid intermittent
Windows localhost disconnects; browser requests default to `localhost:8000`.
Allow the frontend origin in the JSON `CORS_ORIGINS` setting. For HTTPS
hosting set `AUTH_COOKIE_SECURE=true` and serve UI/API through the same hostname.

New chats display **New Chat**, then receive a short topic title from the first
successful question. Later questions and custom titles do not overwrite it.
Questions appear immediately above **Thinking...**. Source entries group chunks
from one document while retaining all cited marker numbers. Retrieval models
warm up before the API accepts requests (`RETRIEVAL_WARMUP=true`); startup is
longer, and cloud-model/CPU latency still depends on the runtime.

The **Supported topics and sources** sidebar panel lists the shared 36-topic
ingestion scope and PubMed, OpenFDA drug labels, and WHO guidelines. Availability
varies across topics and sources. A session can also use its own uploaded PDFs.
Answers match the current question's detected language, with English as the
fallback for ambiguous medical terms. A clearly wrong-language answer is retried
once, then rejected if the mismatch persists. Install the pinned requirements
when updating (`langdetect==1.0.9` was added for local language identification).

See [the Phase 21 UI follow-up](docs/phase21_ui_followup.md) for verification.

CPU reranking now defaults to full-precision ONNX inference using the same
cross-encoder weights, token limit, 20-candidate pool and five final results.
The first startup exports the model into ignored `.medrag_cache/`; subsequent
starts reuse an export identified by its weights/configuration. Keep startup
warmup enabled. Install the updated pinned requirements before restarting the
backend. `RERANK_BACKEND=torch` restores the original runtime;
`RERANK_THREADS=4` controls ONNX CPU threads. No query, answer or private evidence
cache was introduced. See [measured timings](docs/performance_report.md).

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

Phase 22 adds GitHub Actions checks and tested container release publishing.
See [Phase 22 report and release guide](docs/phase22_report.md) for triggers, local
verification, required repository settings and the remaining deployment steps.

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
