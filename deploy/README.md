# Portable Docker deployment for the MedRAG portfolio demo

This prepares a single Linux Docker host with a public domain. It does not create a paid server or deploy automatically. Keep the existing `docker-compose.yml` for local development; use `compose.portable.yml` for hosting.

## What runs

Caddy owns public ports 80/443 and obtains HTTPS certificates. `/api/*` routes to FastAPI; all other paths route to Streamlit, including WebSockets. Frontend and browser authentication share one origin, so the HttpOnly session cookie survives refresh without relying on third-party cookies. The API uses `/api` as its documentation root path. Forwarded headers are trusted only under this stack's private-network assumption; do not expose the API port directly. Only the proxy exposes host ports. PostgreSQL, Neo4j and Qdrant stay on the private data network. All database data, certificates and retrieval model caches use named volumes. The serving image excludes RAGAS, notebook, ingestion-only and test packages.

## Prepare the host

Install Docker Engine and the Compose plugin. Point a domain's DNS to the host and allow inbound TCP 80/443. Initial model downloads need outbound internet. Capacity has not been load-tested; allow room for the CPU retrieval models and three databases rather than choosing the smallest instance blindly.

From the repository root, copy `deploy/portable.env.example` to `deploy/portable.env`. Set the domain, certificate email, OpenAI key and contact email. Generate separate database passwords of at least 20 random characters. Never commit the completed file. Both Git and Docker build context exclude it. Set OpenAI project spending limits before opening a public demo.

```bash
cp deploy/portable.env.example deploy/portable.env
# Edit deploy/portable.env with your actual values.
docker compose --env-file deploy/portable.env -f deploy/compose.portable.yml config --quiet
docker compose --env-file deploy/portable.env -f deploy/compose.portable.yml build api ui
docker compose --env-file deploy/portable.env -f deploy/compose.portable.yml up -d postgres qdrant neo4j
```

Wait for the databases to start before provisioning. Keep the proxy stopped until the corpus and readiness gate pass.

## Provision the curated corpus

Starting an empty database does not supply the corpus. Transfer only the project's curated `data/processed` chunks and precomputed embeddings to the host, or restore a curated-only database backup. Do not copy snapshots containing real user uploads/accounts into a public portfolio demo.

The existing runners use stored embeddings and compute sparse vectors locally; they do not call OpenAI to regenerate embeddings. Run them once with the processed data mounted read-only:

```bash
docker compose --env-file deploy/portable.env -f deploy/compose.portable.yml run --rm --no-deps -v "$PWD/data/processed:/app/data/processed:ro" api python backend/scripts/run_qdrant_ingestion.py
docker compose --env-file deploy/portable.env -f deploy/compose.portable.yml run --rm --no-deps -v "$PWD/data/processed:/app/data/processed:ro" api python backend/scripts/run_graph_ingestion.py
docker compose --env-file deploy/portable.env -f deploy/compose.portable.yml run --rm --no-deps api python deploy/check_readiness.py
```

Do not use the ingestion runner's `--reset` option on a populated deployment: it deletes collection data. The read-only readiness gate requires a compatible dense/sparse collection, visible curated chunks from PubMed/OpenFDA/WHO, and the expected medical graph relationships. `/health` checks connectivity; it is not proof that the corpus is populated.

Once the gate passes:

```bash
docker compose --env-file deploy/portable.env -f deploy/compose.portable.yml up -d
```

Initial warmup/downloads may take several minutes. Check service health and logs before judging response speed.

## Verify before sharing

Open the HTTPS domain and verify sign-in, refresh, a new chat title, PDF upload inventory and chunk retrieval after logout/login (the app retains chunks and metadata, not an original-PDF file archive), and isolation using a second synthetic account. Check an English answer, an Urdu answer table, a verified WHO figure and a source excerpt. Original source excerpts retain their original language. Avoid patient information; use synthetic documents. Check `/api/health` and `/api/docs`; anonymous `/api/sessions` must return 401. Review generated medical wording manually; structural tests do not prove clinical accuracy. Run the read-only route check from an environment with requests installed:

```bash
python deploy/http_smoke.py https://YOUR_DOMAIN
```

It checks health, authentication enforcement, reverse-proxy docs and frontend routes without model queries.

## Updates, backups and rollback

Commit the final changes and wait for their own green GitHub CI run. The latest earlier main run does not verify uncommitted changes. The release workflow publishes tested GHCR images; it does not deploy this host. Set `BACKEND_IMAGE` and `FRONTEND_IMAGE` to immutable release tags/digests and use `docker compose ... pull` followed by `docker compose ... up -d --no-build` for image-based updates.

Before updating, back up PostgreSQL with `pg_dump`, Qdrant with its snapshot API, and Neo4j with its supported backup/dump procedure. Keep backups private and test restoration into separate disposable databases. Retain the previous image digests for rollback; database changes may need a matching restored backup. Never run `down -v` on the live stack: it removes persistent data. Stop with `down` without `-v` when required. Do not erase the project's existing local database folders.

## Verification limits

Public DNS, certificate issuance, hosted browser behavior, a backup restoration and load/cost capacity cannot be verified until a host/domain is selected. This configuration is a portable portfolio deployment starting point, not a claim of a clinically validated production service.
