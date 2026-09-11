# Phase 13: Medical Knowledge Graph (Neo4j) — Report

## Phase Objective

Build a structured drug-disease knowledge graph in Neo4j, extracting explicit relationships (treats, contraindicated in, causes) from OpenFDA drug label data — moving beyond "search for text that mentions both terms" (Phases 6-11) to "directly query a stated fact." Scoped to OpenFDA only, as planned from the project's original architecture, since it is the only source with the structured section metadata needed to classify relationship type reliably.

## What Was Built

- **`extract_relationships_from_chunk()`** — maps an OpenFDA chunk's labeled section (`chunk.metadata['field']`) directly to a relationship type, using the chunk's already-known `source_id` for the drug and NER-extracted `DISEASE` entities for the other side.
- **`normalize_entity()`** — lowercase/whitespace normalization for graph node identity, with original casing preserved for display.
- **`aggregate_relationships()`** — consolidates relationships across the entire corpus, deduplicating by `(drug, relationship, disease)` and collecting every supporting `chunk_id` as an evidence/citation trail.
- **`write_relationships_batched()`** — writes to Neo4j via batched `UNWIND` + `MERGE` Cypher, grouped by relationship type per batch (Cypher cannot parameterize relationship types).
- **`get_neo4j_driver()` / `setup_constraints()`** — connection handling and uniqueness constraints on `Drug`/`Disease` node identity.
- **`backend/src/medrag/knowledge_graph/`** — new package (`neo4j_client.py`, `graph_ingestion.py`, `__init__.py`), plus `run_graph_ingestion.py`.

## Key Design Decisions

1. **OpenFDA-only scope, decided at project inception and confirmed correct during this phase.** WHO and PubMed chunks are unstructured prose with no equivalent section labeling — reliably classifying relationship type from free text would require verb/proximity-based inference with real false-positive risk. OpenFDA's `field` metadata (set during Phase 5 chunking) gives relationship type directly from the source's own structure, with no inference needed.
2. **Field-to-relationship mapping is deliberately incomplete.** Of OpenFDA's 7 distinct section types, only 4 map to a relationship (`indications_and_usage`→`TREATS`, `contraindications`→`CONTRAINDICATED_IN`, `adverse_reactions`/`warnings_and_cautions`→`CAUSES`). `mechanism_of_action` (diseases mentioned there are usually incidental biological context, not a direct relationship), `dosage_and_administration` (dosing conditions, not relationships), and `drug_interactions` (relates two drugs to each other — a genuinely different relationship type, out of this phase's scope) are excluded on purpose.
3. **The drug side of every relationship comes from `chunk.source_id`, never from NER-extracted `CHEMICAL` entities.** An initial version extracted both sides via NER and paired every `CHEMICAL` × `DISEASE` entity found in a chunk (a cartesian product). This was tested on real data and found to produce clearly false relationships (e.g. "Vitamin B CAUSES lactic acidosis," from a passage where vitamin B12 and lactic acidosis merely co-occurred without any real relationship) and fragmented one drug into multiple node identities based on incidental text phrasing (`metformin` / `Metformin` / `Metformin hydrochloride` as three separate nodes). Since every chunk in a drug's label document already carries one known, canonical `source_id` from Phase 5 chunking, the fix was to stop extracting the chemical from text entirely — NER is only needed for the disease side. This dropped a real test case from 83 relationships (many wrong) to 25 (all correct).
4. **Entity names normalized for node identity, original casing preserved for display.** Confirmed necessary by direct observation: case variants (`Hypoglycemia` vs. `hypoglycemia`) were creating duplicate graph nodes for the same real-world entity before this was added.
5. **Cross-chunk aggregation with evidence tracking, not per-chunk relationship creation.** A fact stated in multiple chunks (e.g. a drug's warning appearing in both a summary and a detailed section) becomes one graph edge carrying every supporting `chunk_id`, rather than multiple duplicate edges — giving a citation trail back to source text and a rough measure of how strongly a fact is supported.
6. **Batched `UNWIND` writes over one query per relationship**, matching the batching discipline established in Phase 6/8 — writing ~49,000 relationships individually would be far slower than grouping them into large per-type transactions.

## Results

- **Test-case validation on Metformin** (8 real chunks) confirmed the full pipeline end-to-end: 25 relationships after the source_id fix, 23 after per-chunk case-normalization, 19 after final cross-chunk aggregation — all 19 verified as genuinely correct via direct Cypher query-back from Neo4j itself, including a case (`renal impairment`) correctly represented as one Disease node connected by two different, both-valid relationship types (`CONTRAINDICATED_IN` and `CAUSES`) rather than duplicated.
- **Full-scale run**: 13,167 OpenFDA chunks processed → 79,727 raw relationships → 49,133 unique relationships after aggregation (a ~38% reduction from deduplication, consistent with the pattern seen at test-case scale).
- **Final graph**: 466 `Drug` nodes, 7,069 `Disease` nodes, 49,133 relationships (`CAUSES`: 42,206, `TREATS`: 5,125, `CONTRAINDICATED_IN`: 1,802).
- **466 vs. the expected 467 unique OpenFDA drugs was investigated, not assumed benign.** Confirmed no entity-normalization collisions (no two different drugs merged into one node). Traced to a single drug (`R Cos`) whose only qualifying section text mentioned exclusively `COVID-19` and `MERS` — neither recognized as a `DISEASE` entity by `en_ner_bc5cdr_md`, whose training corpus predates COVID-19. A genuine, narrow, and now-documented NER limitation affecting exactly one drug, not a pipeline bug.
- **Production `run_graph_ingestion.py` verified to exactly reproduce the notebook's final graph counts** (466 / 7,069 / 49,133) after fixing a path-resolution bug (see below).

## Challenges & Solutions

- **A cartesian-product relationship extraction bug was found and fixed via direct inspection of real output**, not assumed correct after passing a syntax check — see Design Decision 3. This was the most significant fix of the phase and fundamentally changed the extraction approach for the better.
- **A project-wide path-handling bug was discovered while verifying this phase's production script.** `run_graph_ingestion.py` initially loaded 0 chunks (silently, no error) when run from `backend/`, despite every prior runner script's docstring claiming "run from the backend/ folder." Investigation confirmed the actual data directory lives at the project root (`medrag/data/...`), not under `backend/` — meaning prior scripts using the bare relative path `"data/processed/chunks"` had only ever appeared to work because they happened to be run from the project root, not `backend/`, contradicting their own documented usage instructions. Fixed in this phase's script with a `find_project_root()`-anchored path (the same robust pattern already used in every notebook), rather than patching around it again with another workaround. This is the first production script to use this pattern; earlier scripts (`run_qdrant_ingestion.py` and others) were not retroactively updated and carry the same latent fragility — worth revisiting in a future cleanup pass.
- **A `ModuleNotFoundError` for `config.settings`** occurred because this is the first runner script to import Neo4j credentials from settings — earlier scripts never needed `config/`, so the missing `backend/` entry on `sys.path` had never surfaced before. Fixed with an explicit `sys.path` insert anchored to the discovered project root.
- **Neo4j `AuthError` from an empty password** — traced to `.env` having a blank value after `NEO4J_PASSWORD=` and to `settings` being a singleton loaded once at import time, meaning a running kernel doesn't pick up `.env` changes without a restart.

## Files Created

- `backend/src/medrag/knowledge_graph/__init__.py`
- `backend/src/medrag/knowledge_graph/neo4j_client.py` (`get_neo4j_driver`, `setup_constraints`)
- `backend/src/medrag/knowledge_graph/graph_ingestion.py` (`normalize_entity`, `FIELD_TO_RELATIONSHIP`, `extract_relationships_from_chunk`, `aggregate_relationships`, `write_relationships_batched`)
- `backend/scripts/run_graph_ingestion.py`
- `notebooks/phase14_knowledge_graph.ipynb`
- Neo4j graph database, persisted in a volume-mounted Docker container (`neo4j_data/`, gitignored)