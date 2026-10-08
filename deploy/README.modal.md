# Modal portfolio deployment

This target keeps the Streamlit interface and FastAPI backend behind one HTTPS URL. Modal runs the app on CPU, with zero minimum containers and one maximum container. PostgreSQL, Qdrant and Neo4j remain persistent external databases. Local Docker stays available.

## 1. Create cloud databases

The databases running on your laptop are not reachable from Modal. Create dedicated demo databases, preserving the originals:

- Qdrant Cloud Free: obtain the HTTPS endpoint and API key.
- Neo4j AuraDB Free: obtain the `neo4j+s://` address and credentials. The saved graph has 7,535 nodes and 49,133 edges; check current plan limits before importing.
- Neon Free PostgreSQL: obtain host, port, database, username and password. Use the direct connection endpoint for schema creation, and require TLS.

Free plans can suspend or delete inactive databases. They do not guarantee an always-ready demo. Check and reactivate them before interviews. Do not copy real accounts or private uploaded documents.

## 2. Modal settings

Install the isolated tooling (already prepared in this checkout):

```powershell
python -m venv .modal-venv
.\.modal-venv\Scripts\python.exe -m pip install -r deploy/requirements-modal.txt
.\.modal-venv\Scripts\modal.exe token new
```

If already authenticated, skip `token new`. Never paste tokens into a chat or commit them.

In the Modal dashboard, create Secret **medrag-demo**, using the names in `deploy/modal.env.example`. Fill the OpenAI key and cloud database credentials. Set `PGSSLMODE=require`. Initially set `MEDRAG_PUBLIC_ORIGIN` to `https://example.com`; do not visit the demo while using this placeholder.

```powershell
.\.modal-venv\Scripts\modal.exe deploy deploy/modal_app.py
```

Use the actual HTTPS URL printed by Modal as `MEDRAG_PUBLIC_ORIGIN` in the Secret, without an `/api` suffix. Redeploy after updating the Secret. The origin is required for secure cookie authentication. Keep `MEDRAG_DEMO_READY=false`; the public app is disabled until provisioning passes. Credentials never belong in frontend code.

## 3. Provision the corpus once

Before sharing the URL, initialize only the curated corpus in your dedicated demo databases:

```powershell
.\.modal-venv\Scripts\modal.exe run deploy/modal_app.py::provision
```

This uses saved embeddings and the fingerprint-checked OpenFDA graph, then checks the corpus. It never calls `--reset` or deliberately copies private user data. Ingestion upserts into the configured databases; ensure the Secret points to the new demo databases. Do not run concurrent provisioning jobs.

After successful provisioning, set `MEDRAG_DEMO_READY=true` in the Modal Secret and redeploy.

## 4. Verify the hosted demo

Open the Modal URL, sign in and verify refresh, saved chats, private PDF inventory, source tables/figures and cross-account isolation. API docs are at `/api/docs`. Run the existing read-only HTTP smoke check against the URL. Review wording manually; software checks do not prove clinical accuracy.

## Cost and idle behavior

Starter currently includes $30/month compute credit shared by apps in the workspace. Load time, active requests and the idle grace period consume usage. The app can scale to zero after requests/connections finish. Streamlit uses WebSockets, so an open browser tab can keep it active; it is not billed only when a question is submitted. Connections have a bounded lifetime and may require refresh. The first visit loads retrieval models and can be slower.

No GPU is requested. Model files are cached in a Modal Volume; these are caches, not chat storage. Persistent user data remains in the external databases. OpenAI and database-provider charges are separate. Keep usage within the available credits; this setup is not a guarantee of zero cost. No automatic background keepalive is configured.

## Status

Source/configuration can be verified locally. A real deployment, cloud corpus import, hosted cookie behavior and measured credit consumption require the cloud endpoints and Secret. Do not claim the demo is live until those checks pass.
