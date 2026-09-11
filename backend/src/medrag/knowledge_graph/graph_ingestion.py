"""
Extracts drug-disease relationships from OpenFDA chunks and writes them
to Neo4j as a knowledge graph.

Scope: OpenFDA only, deliberately. This was decided during Phase 14
development after directly comparing extraction reliability across
sources: OpenFDA drug labels have consistent, structured sections
(field metadata set during Phase 5 chunking - e.g. "indications_and_usage",
"contraindications") that state a drug-disease relationship directly and
unambiguously. WHO/PubMed text has no equivalent structure - extracting
a reliable relationship type from free prose would require verb/pattern
detection with real false-positive risk, which was explicitly scoped
out of this phase's initial plan. This is a deliberate, documented scope
boundary, not an oversight - matching the project's established pattern
(e.g. the WHO 12-topic coverage gap) of stating real limitations plainly.

Two design decisions were validated directly against real data before
being adopted, and are important not to regress:

1. The drug side of every relationship comes from chunk.source_id, NOT
   from NER-extracted CHEMICAL entities. An earlier version extracted
   chemicals from chunk text and paired every CHEMICAL x DISEASE entity
   found in a chunk (a cartesian product) - this produced clearly wrong
   relationships (e.g. "Vitamin B CAUSES lactic acidosis", extracted
   from a passage about vitamin B12 deficiency that only mentioned
   lactic acidosis elsewhere in the same chunk) and fragmented one drug
   into multiple node identities based on incidental text phrasing
   (metformin / Metformin / Metformin hydrochloride). Since every chunk
   in a drug's label document already shares one known, canonical
   source_id (set during Phase 5 chunking), the chemical side never
   needs to be extracted or guessed from text at all - only the disease
   side needs NER.

2. Entity names are normalized (lowercase, stripped) for graph node
   identity, with the first-seen original casing preserved for display.
   Without this, case variants (Hypoglycemia / hypoglycemia) were
   confirmed to create duplicate graph nodes for what is the same
   real-world entity.
"""

import logging
from collections import defaultdict
from typing import List, Dict

from neo4j import Driver

from medrag.ner.ner import extract_medical_entities
from medrag.processing.models import Chunk

logger = logging.getLogger("medrag.knowledge_graph")

# Maps an OpenFDA label section (chunk.metadata['field']) directly to a
# relationship type. Deliberately incomplete: mechanism_of_action,
# dosage_and_administration, and drug_interactions are excluded - see
# module docstring in the Phase 14 notebook / phase report for why each
# was excluded (dosing/mechanism text doesn't state a drug-disease
# relationship worth graphing; drug_interactions relates two drugs to
# each other, a different relationship type out of this phase's scope).
FIELD_TO_RELATIONSHIP = {
    "indications_and_usage": "TREATS",
    "contraindications": "CONTRAINDICATED_IN",
    "adverse_reactions": "CAUSES",
    "warnings_and_cautions": "CAUSES",
}

DEFAULT_BATCH_SIZE = 500


def normalize_entity(name: str) -> str:
    """Normalize an entity name for deduplication/graph-node identity.
    Case differences are a text-casing artifact, not a different
    real-world entity - confirmed necessary by finding duplicate nodes
    (Hypoglycemia vs hypoglycemia) without this step."""
    return name.strip().lower()


def extract_relationships_from_chunk(chunk: Chunk) -> List[dict]:
    """Extract (drug, relationship, disease) tuples from one OpenFDA
    chunk. Returns an empty list for chunks whose field isn't in
    FIELD_TO_RELATIONSHIP (deliberate scope exclusion) or for chunks
    where NER finds no DISEASE entities (a real, narrow, and expected
    occurrence - e.g. confirmed on one real drug entry whose only
    qualifying text mentioned only COVID-19/MERS, neither of which
    en_ner_bc5cdr_md recognizes as a DISEASE entity, since its training
    corpus predates COVID-19)."""
    field = chunk.metadata.get("field") if chunk.metadata else None
    relationship_type = FIELD_TO_RELATIONSHIP.get(field)
    if relationship_type is None:
        return []

    drug_name = chunk.source_id
    entities = extract_medical_entities(chunk.raw_text)

    # dedupe by normalized form within this chunk, keep first-seen
    # original casing for display
    seen_normalized: Dict[str, str] = {}
    for disease in entities["diseases"]:
        norm = normalize_entity(disease)
        if norm not in seen_normalized:
            seen_normalized[norm] = disease

    return [
        {
            "chemical": drug_name,
            "chemical_normalized": normalize_entity(drug_name),
            "relationship": relationship_type,
            "disease": original_disease,
            "disease_normalized": norm_disease,
            "source_chunk_id": chunk.chunk_id,
        }
        for norm_disease, original_disease in seen_normalized.items()
    ]


def aggregate_relationships(all_relationships: List[dict]) -> List[dict]:
    """Consolidate relationships across ALL chunks (not just within
    one), keyed by (chemical_normalized, relationship, disease_normalized).
    Multiple chunks asserting the same fact become one edge with
    multiple source_chunk_ids as evidence - stronger support for a fact
    stated repeatedly, and a citation trail back to source text."""
    grouped = defaultdict(lambda: {
        "source_chunk_ids": [],
        "display_disease": None,
        "display_chemical": None,
    })

    for r in all_relationships:
        key = (r["chemical_normalized"], r["relationship"], r["disease_normalized"])
        entry = grouped[key]
        entry["source_chunk_ids"].append(r["source_chunk_id"])
        if entry["display_disease"] is None:
            entry["display_disease"] = r["disease"]
            entry["display_chemical"] = r["chemical"]

    return [
        {
            "chemical": entry["display_chemical"],
            "chemical_normalized": chem_norm,
            "relationship": rel,
            "disease": entry["display_disease"],
            "disease_normalized": dis_norm,
            "source_chunk_ids": entry["source_chunk_ids"],
        }
        for (chem_norm, rel, dis_norm), entry in grouped.items()
    ]


def write_relationships_batched(
    driver: Driver,
    relationships: List[dict],
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> int:
    """Write relationships to Neo4j in batches via UNWIND, grouped by
    relationship type within each batch. Relationship type is inserted
    via an f-string into the Cypher query text (Cypher cannot
    parameterize relationship types, only property values) - this is
    safe here specifically because the value only ever comes from our
    own fixed FIELD_TO_RELATIONSHIP dict, never from extracted text or
    user input."""
    with driver.session() as session:
        for i in range(0, len(relationships), batch_size):
            batch = relationships[i:i + batch_size]

            by_type = defaultdict(list)
            for r in batch:
                by_type[r["relationship"]].append(r)

            for rel_type, rows in by_type.items():
                session.run(
                    f"""
                    UNWIND $rows AS row
                    MERGE (d:Drug {{normalized_name: row.chemical_normalized}})
                    ON CREATE SET d.name = row.chemical
                    MERGE (dis:Disease {{normalized_name: row.disease_normalized}})
                    ON CREATE SET dis.name = row.disease
                    MERGE (d)-[rel:{rel_type}]->(dis)
                    SET rel.source_chunk_ids = row.source_chunk_ids
                    """,
                    rows=rows,
                )
            logger.info(f"  wrote {min(i + batch_size, len(relationships))}/{len(relationships)}")

    return len(relationships)