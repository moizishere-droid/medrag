# Run the full MedRAG app locally with Docker

Requires Docker Desktop (Linux containers) or Docker Engine with Compose, internet access for the first build/model downloads, and your own OpenAI API key. These are local builds, not published registry images. Model calls incur your API account's charges.

This stack uses separate named database volumes under `medrag-local`. It does not reuse or modify the existing development database folders. Only the browser port is exposed, on loopback. This HTTP setup is for your computer; use the portable HTTPS configuration for public hosting.

## First-time setup (PowerShell, repository root)

```powershell
git clone https://github.com/moizishere-droid/medrag.git
cd medrag
Copy-Item deploy/local.env.example deploy/local.env
notepad deploy/local.env
```

Fill `OPENAI_API_KEY`, `PUBMED_EMAIL`, and two different database passwords (20+ characters recommended). Keep the file private. If this folder already exists, skip cloning. Do not overwrite a completed credentials file.

The repository currently tracks the curated chunks and saved embeddings under `data/processed`. Keep those files when cloning (including any Git LFS artifacts, if configured). The startup helper checks for them, waits for the databases, provisions the curated vectors and graph once, and checks source counts before starting the API. The prepared OpenFDA graph is verified against the exact chunk-file fingerprint and source IDs; when present it avoids repeating full NER extraction. Later starts reuse the ready corpus. It never uses `--reset` or removes existing accounts/uploads. Saved embeddings are reused without paid embedding regeneration. First-time graph/vector ingestion and model downloads can take several minutes.

## Start the complete app

After the first-time setup, this is the single startup command:

```powershell
docker compose --env-file deploy/local.env -f deploy/compose.local.yml up -d --build
```

Open http://localhost:8501 (use this hostname for browser authentication). API docs are at http://localhost:8501/api/docs. Startup warms the retrieval models and may take several minutes initially. If port 8501 is occupied, set `MEDRAG_LOCAL_PORT=8503` in `deploy/local.env` and run the startup command again. Open http://localhost:8503 instead; browser authentication origins and API URLs follow the configured port.

```powershell
docker compose --env-file deploy/local.env -f deploy/compose.local.yml ps
docker compose --env-file deploy/local.env -f deploy/compose.local.yml logs --tail=100 bootstrap api ui proxy
```

Health reports connectivity, not full corpus availability or medical answer quality. Register a synthetic account and verify chat, refresh, upload inventory and source media before sharing a demo.

To stop while retaining data:

```powershell
docker compose --env-file deploy/local.env -f deploy/compose.local.yml down
```

Never add `-v` unless you intentionally want to delete this stack's database and cache volumes. Changing password settings does not change passwords inside already initialized databases.
