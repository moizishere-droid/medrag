# MedRAG — Multilingual Multimodal Medical Knowledge RAG System

Production-grade RAG system that ingests free, public medical literature (PubMed, WHO guidelines, OpenFDA) and answers questions across **text, images, and tables**, in the user's own language (English, Arabic, French, German, Spanish, Urdu).

See [`docs/phase00_report.md`](docs/phase00_report.md) for the full project documentation: problem statement, solution, architecture, tech stack, and phase plan.

## Status
🚧 Phase 0 — Project Documentation & Architecture (complete)

## Setup
```bash
# Windows
install.bat

# then
cp .env.example .env
# fill in your API keys
```

## Tech Stack
GPT-4-turbo · OpenAI Embeddings · CLIP · Qdrant · Neo4j · PostgreSQL · SpaCy/scispaCy · FastAPI · Streamlit · Docker · RAGAS

## License
TBD
