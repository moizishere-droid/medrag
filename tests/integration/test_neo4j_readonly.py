"""Read-only integration tests against the REAL knowledge graph.

Neo4j Community edition has a single database, so there is no safe place to write
test data. These tests therefore only READ, and assert invariants that
generation.py depends on rather than exact counts (which change on re-ingestion).
"""

import importlib

import pytest
from neo4j import GraphDatabase

from config.settings import settings

pytestmark = pytest.mark.integration

gen = importlib.import_module("medrag.generation.generation")

ALLOWED_RELATIONSHIPS = {"TREATS", "CONTRAINDICATED_IN", "CAUSES"}
SAMPLE_SIZE = 25


@pytest.fixture(scope="module")
def driver():
    if not (settings.neo4j_uri and settings.neo4j_user and settings.neo4j_password):
        pytest.fail("Neo4j settings missing (NEO4J_URI/USER/PASSWORD in .env)")
    drv = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
    try:
        drv.verify_connectivity()
    except Exception as exc:
        drv.close()
        pytest.fail(f"Cannot reach Neo4j. Is `docker compose up` running? ({exc})")
    yield drv
    drv.close()


@pytest.fixture
def drug_names(driver, monkeypatch):
    # get_all_known_drug_names caches at module level; restore it after this test
    monkeypatch.setattr(gen, "_known_drug_names_cache", None)
    return gen.get_all_known_drug_names(driver, use_cache=False)


def test_drug_names_are_present_clean_and_unique(drug_names):
    assert drug_names, "the graph has no Drug nodes"
    assert all(isinstance(n, str) and n.strip() for n in drug_names)
    normalised = [n.strip().lower() for n in drug_names]
    assert len(normalised) == len(set(normalised))


def test_every_drug_has_the_normalised_name_that_lookups_depend_on(driver):
    """get_graph_facts_for_drug matches on normalized_name = name.strip().lower(),
    the same normalisation as ingestion. A mismatch makes a drug's facts unreachable."""
    with driver.session() as session:
        mismatches = session.run(
            "MATCH (d:Drug) WHERE d.normalized_name IS NULL "
            "OR d.normalized_name <> toLower(trim(d.name)) RETURN count(d) AS n"
        ).single()["n"]
    assert mismatches == 0


def test_the_graph_links_drugs_to_diseases(driver):
    with driver.session() as session:
        count = session.run("MATCH (:Drug)-[r]->(:Disease) RETURN count(r) AS n").single()["n"]
    assert count > 0


def test_curated_facts_honour_their_contract_for_a_sample_of_real_drugs(driver, drug_names):
    for name in drug_names[:SAMPLE_SIZE]:
        facts = gen.get_graph_facts_for_drug_curated(driver, name)

        assert {f["relationship"] for f in facts} <= ALLOWED_RELATIONSHIPS, name
        treats = {f["disease"].lower() for f in facts if f["relationship"] == "TREATS"}
        causes = [f for f in facts if f["relationship"] == "CAUSES"]
        assert not treats & {f["disease"].lower() for f in causes}, f"{name}: TREATS/CAUSES overlap"
        assert len(causes) <= gen.DEFAULT_MAX_CAUSES, name