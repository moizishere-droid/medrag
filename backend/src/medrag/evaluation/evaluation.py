"""
RAGAS-based evaluation of the retrieval + generation pipeline against a
hand-verified test set (data/eval/ragas_test_set.json).

Deliberately separates two model roles that must never be confused:
  - The PRODUCTION generation model (gpt-4.1-nano, Phase 14) generates
    every answer being evaluated - this module never changes what the
    system itself uses to answer questions.
  - The JUDGE model (configurable here, defaults to a stronger/pricier
    model such as gpt-5.2) only SCORES those already-generated answers.
    Using a stronger judge for this one-time evaluation is a reasonable,
    low-cost choice (a handful of short judge calls total) even though
    the same stronger model would be too expensive to use for every
    real production query.

Known, load-bearing limitation - read before trusting any reported
context_recall number: this metric was found to be genuinely unreliable
during Phase 17 development, with BOTH gpt-4.1-nano and gpt-5.2 as
judge. With gpt-4.1-nano, it returned a flat 1.0 across every row,
including rows that scored 0 on every other metric - an impossible
combination if taken at face value. With gpt-5.2, a specific row
(ACE inhibitor side effects) that was manually verified to have every
ground-truth claim actually present in the retrieved context still
scored 0.0 - and re-running the identical row three times in a row
produced 0.0, 0.0, then 1.0, on unchanged input. This is not measurement
noise around a stable true value; it is outright non-determinism on the
exact same question. context_recall results from this module should be
reported as unreliable/exploratory, not as a trustworthy score, until a
different metric implementation or judge is validated. The other three
metrics (faithfulness, answer_relevancy, context_precision) did not show
this behavior and are considered reportable.

A required workaround before importing ragas: apply_vertexai_stub()
must be called before any `import ragas` (directly or transitively).
This works around a confirmed, currently-open upstream bug where ragas
imports ChatVertexAI from a langchain_community path that no longer
exists in any current langchain-community release - unrelated to this
project's code, and unrelated to whether VertexAI is actually used
(it isn't).
"""

import json
import logging
import sys
import types
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("medrag.evaluation")

DEFAULT_CANDIDATE_POOL_SIZE = 20
DEFAULT_TOP_N = 5

# Metrics considered reliable enough to report, based on Phase 17
# investigation (see module docstring). context_recall is deliberately
# excluded from the default set.
RELIABLE_METRIC_NAMES = ["faithfulness", "answer_relevancy", "context_precision"]
UNRELIABLE_METRIC_NAMES = ["context_recall"]


def apply_vertexai_stub() -> None:
    """Insert a stub for langchain_community.chat_models.vertexai into
    sys.modules before ragas is imported. Works around a confirmed,
    currently-open upstream ragas bug (ragas/llms/base.py still imports
    ChatVertexAI from a path removed from every current
    langchain-community release - see e.g. github.com/vibrantlabsai/
    ragas issues #2745, #2753, #2995). This project never uses
    VertexAI; the stub class raises if anyone ever tries to actually
    instantiate it, so a real attempt to use VertexAI would fail loudly
    rather than silently doing nothing."""
    if "langchain_community.chat_models.vertexai" in sys.modules:
        return  # already applied

    stub = types.ModuleType("langchain_community.chat_models.vertexai")

    class ChatVertexAI:
        def __init__(self, *args, **kwargs):
            raise NotImplementedError(
                "VertexAI is not used in this project - this is a stub "
                "inserted only to satisfy ragas's broken import."
            )

    stub.ChatVertexAI = ChatVertexAI
    sys.modules["langchain_community.chat_models.vertexai"] = stub
    logger.info("Applied langchain_community.chat_models.vertexai stub (ragas upstream workaround)")


def load_test_set(path: str) -> List[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run_pipeline_on_test_set(
    test_set: List[dict],
    qdrant_client,
    openai_client,
    neo4j_driver=None,
    generation_model: str = "gpt-4.1-nano",
    candidate_pool_size: int = DEFAULT_CANDIDATE_POOL_SIZE,
    top_n: int = DEFAULT_TOP_N,
) -> List[dict]:
    """Run every test question through the real, production retrieval +
    generation pipeline (Phases 10/11/14), collecting what RAGAS needs:
    the question, the generated answer, the retrieved context texts, and
    the reference ground truth. generation_model defaults to the actual
    production model (gpt-4.1-nano) - this function evaluates the real
    system, not a hypothetical stronger one."""
    from medrag.retrieval.reranking import search_with_reranking
    from medrag.generation.generation import generate_answer

    records = []
    for item in test_set:
        question = item["question"]
        logger.info(f"Processing: {question}")

        results = search_with_reranking(
            qdrant_client, question,
            candidate_pool_size=candidate_pool_size, top_n=top_n,
        )
        contexts = [r["payload"]["raw_text"] for r in results]

        answer = generate_answer(
            question,
            qdrant_client=qdrant_client,
            openai_client=openai_client,
            neo4j_driver=neo4j_driver,
            model=generation_model,
        )

        records.append({
            "question": question,
            "answer": answer,
            "contexts": contexts,
            "ground_truth": item["ground_truth"],
        })

    logger.info(f"Collected {len(records)} eval records")
    return records


def run_ragas_evaluation(
    eval_records: List[dict],
    openai_api_key: str,
    judge_model: str = "gpt-5.2",
    include_unreliable_metrics: bool = False,
):
    """Build a RAGAS dataset from eval_records and score it with
    judge_model. include_unreliable_metrics=False (default) only runs
    the three metrics found reliable during Phase 17 development
    (faithfulness, answer_relevancy, context_precision); pass True to
    also include context_recall, understanding its results should be
    treated as exploratory/unreliable rather than reported at face
    value (see module docstring)."""
    apply_vertexai_stub()

    from datasets import Dataset
    from ragas import evaluate
    from ragas.metrics import faithfulness, answer_relevancy, context_precision, context_recall
    from ragas.llms import LangchainLLMWrapper
    from langchain_openai import ChatOpenAI

    metrics = [faithfulness, answer_relevancy, context_precision]
    if include_unreliable_metrics:
        metrics.append(context_recall)
        logger.warning(
            "context_recall included - treat its results as unreliable/exploratory, "
            "not a trustworthy score (see module docstring for why)."
        )

    dataset = Dataset.from_list(eval_records)
    judge_llm = LangchainLLMWrapper(ChatOpenAI(model=judge_model, api_key=openai_api_key))

    return evaluate(dataset, metrics=metrics, llm=judge_llm, raise_exceptions=True)