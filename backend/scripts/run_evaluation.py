"""
Runner script: evaluates the production retrieval + generation pipeline
against the hand-verified test set using RAGAS, and saves both the
per-question and aggregate results.

Run from the backend/ folder:
    cd backend
    python scripts/run_evaluation.py

Model roles (do not confuse these - see evaluation.py's module
docstring for the full reasoning):
    --generation-model : the model whose ANSWERS are being evaluated.
                          Defaults to gpt-4.1-nano, the real production
                          model (Phase 14) - this script evaluates the
                          actual system, not a hypothetical one.
    --judge-model       : the model used only to SCORE those answers.
                          Defaults to gpt-5.2. A stronger/pricier judge
                          is a reasonable one-time cost for a single
                          evaluation run, even though it would be too
                          expensive to use for every real query.

context_recall is excluded from the default metric set - see
evaluation.py's module docstring for the investigation that found it
unreliable (non-deterministic results on identical input, verified
against both gpt-4.1-nano and gpt-5.2 as judge). Pass
--include-unreliable-metrics to include it anyway, understanding its
results should be treated as exploratory, not a trustworthy score.

Reads:
  - data/eval/ragas_test_set.json (hand-verified test questions)
Writes:
  - data/eval/results.json (per-question scores + aggregate summary)
"""

import argparse
import json
import logging
import sys
from pathlib import Path


def find_project_root(marker: str = "backend", start: Path = None) -> Path:
    current = (start or Path(__file__).resolve()).parent
    for candidate in [current, *current.parents]:
        if (candidate / marker).is_dir():
            return candidate
    raise RuntimeError(f"Could not find a '{marker}' folder above {current}")


PROJECT_ROOT = find_project_root()
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

from config.settings import settings
from medrag.embeddings.qdrant_client import get_qdrant_client
from medrag.evaluation.evaluation import (
    load_test_set,
    run_pipeline_on_test_set,
    run_ragas_evaluation,
    UNRELIABLE_METRIC_NAMES,
)

import openai
from neo4j import GraphDatabase

logging.basicConfig(level=logging.INFO, format="%(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("medrag.evaluation")

EVAL_DIR = PROJECT_ROOT / "data" / "eval"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--generation-model", default="gpt-4.1-nano")
    parser.add_argument("--judge-model", default="gpt-5.2")
    parser.add_argument("--include-unreliable-metrics", action="store_true")
    args = parser.parse_args()

    qdrant = get_qdrant_client(settings.qdrant_url or "http://localhost:6333")
    neo4j_driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
    openai_client = openai.OpenAI(api_key=settings.openai_api_key)

    test_set = load_test_set(str(EVAL_DIR / "ragas_test_set.json"))
    logger.info(f"Loaded {len(test_set)} test questions")

    eval_records = run_pipeline_on_test_set(
        test_set, qdrant, openai_client, neo4j_driver=neo4j_driver,
        generation_model=args.generation_model,
    )

    logger.info(f"Scoring with judge model: {args.judge_model}")
    result = run_ragas_evaluation(
        eval_records,
        openai_api_key=settings.openai_api_key,
        judge_model=args.judge_model,
        include_unreliable_metrics=args.include_unreliable_metrics,
    )

    logger.info(f"Aggregate results: {result}")
    if args.include_unreliable_metrics:
        logger.warning(
            f"Reminder: {UNRELIABLE_METRIC_NAMES} was included but is NOT reliable - "
            "see evaluation.py's module docstring before reporting this number."
        )

    df = result.to_pandas()
    output = {
        "generation_model": args.generation_model,
        "judge_model": args.judge_model,
        "aggregate": {k: v for k, v in dict(result).items()},
        "per_question": df.to_dict(orient="records"),
    }

    output_path = EVAL_DIR / "results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)
    logger.info(f"Saved full results to {output_path}")


if __name__ == "__main__":
    main()