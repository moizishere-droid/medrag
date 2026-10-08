# Manual development setup

For Docker, use [the full-app quickstart](README.local.md). These instructions run Python services directly.

## Local setup

### Prerequisites

- **Python 3.11** is the verified runtime; package metadata supports 3.10â€“3.12.
- Docker with Compose for PostgreSQL, Qdrant and Neo4j.
- OpenAI API key and PubMed contact email.
- Internet access for initial dependencies/model downloads. Live AI calls incur charges.

### 1. Clone and install

```bash
git clone https://github.com/moizishere-droid/medrag.git
cd medrag
```

Windows PowerShell:

```powershell
.\install.bat
.\venv\Scripts\Activate.ps1
Copy-Item .env.example .env
$env:PYTHONPATH = "backend;backend/src"
```

Linux/macOS:

```bash
python3.11 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
python -m pip install -e . --no-deps
cp .env.example .env
export PYTHONPATH=backend:backend/src
```

### 2. Configure `.env`

Fill the template without committing credentials:

| Setting | Purpose |
|---|---|
| `OPENAI_API_KEY`, `PUBMED_EMAIL` | Required settings |
| `NCBI_API_KEY`, `OPENFDA_API_KEY` | Optional ingestion credentials |
| `QDRANT_URL` | Vector database address |
| `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` | Graph connection |
| `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Account/chat database connection |
| `AUTH_REQUIRED` | Defaults to true; keep enabled when hosted |
| `AUTH_TOKEN_HOURS` | Token/cookie lifetime; default 24 hours |
| `AUTH_COOKIE_SECURE`, `CORS_ORIGINS` | HTTPS cookies and exact allowed frontend origins |
| `MEDRAG_API_URL` | Backend address reachable by Streamlit |
| `MEDRAG_BROWSER_API_URL` | Backend address reachable by the browser |
| `RETRIEVAL_WARMUP` | Load retrieval models before accepting requests |
| `RERANK_BACKEND`, `RERANK_THREADS` | Defaults: ONNX and four CPU threads |

Example database passwords and open ports are for local development. Hosting requires private networking and new secrets. Use the same browser hostname for frontend/API to restore login cookies; localhost on both works with different local ports. Set `AUTH_COOKIE_SECURE=true` with HTTPS.

### 3. Start databases and populate the corpus

```bash
docker compose up -d
```

The API initializes its PostgreSQL application schema. Qdrant and the curated Neo4j graph must be populated before meaningful retrieval. Given prepared artifacts, indexing entry points are:

```bash
python backend/scripts/run_qdrant_ingestion.py
python backend/scripts/run_graph_ingestion.py
```

Read the scripts and [Qdrant](../docs/phase09_report.md)/[graph](../docs/phase13_report.md) reports before running against existing databases. Do not use collection-reset options on databases containing uploads.

To reproduce source/artifact preparation, follow the phase reports and notebooks. Entry points include:

```bash
python backend/scripts/run_ingestion.py
python backend/scripts/run_openfda_ingestion.py
python backend/scripts/run_who_ingestion.py
python backend/scripts/run_chunking.py
python backend/scripts/run_embeddings.py
python backend/scripts/run_image_embeddings.py
python backend/scripts/run_image_chunk_linking.py
```

These steps can download substantial data and consume paid embedding calls. They are not required on every restart; use existing artifacts when appropriate.

### 4. Start the application

In the configured environment:

```bash
python -m uvicorn medrag.api.main:app --app-dir backend/src --host 127.0.0.1 --port 8000
```

In a second terminal, activate the environment and run:

```bash
python -m streamlit run frontend/streamlit_app.py
```

- UI: [http://localhost:8501](http://localhost:8501)
- API documentation: [http://localhost:8000/docs](http://localhost:8000/docs)
- Health: [http://localhost:8000/health](http://localhost:8000/health)

Register, create a chat and ask a question. Optionally upload a text-based PDF. Initial startup includes model loading or ONNX export; subsequent starts reuse local model caches.

