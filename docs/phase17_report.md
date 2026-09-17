# Phase 17: RAGAS Evaluation — Report

## Phase Objective

Move from manual, spot-check validation (Phases 10-16) to quantitative evaluation: measure retrieval and generation quality using RAGAS, a standard RAG evaluation framework, against a hand-verified test set — giving defensible, measured numbers rather than qualitative impressions.

## What Was Built

- **`data/eval/ragas_test_set.json`** — 18 hand-verified (question, ground truth) pairs spanning all three data sources, plus deliberate weak-coverage cases.
- **`apply_vertexai_stub()`** — a required workaround for a confirmed, currently-open upstream bug in `ragas`.
- **`run_pipeline_on_test_set()`** — runs every test question through the real, production retrieval + generation pipeline (Phases 10/11/14), collecting exactly what RAGAS needs.
- **`run_ragas_evaluation()`** — builds a RAGAS dataset and scores it, with an explicit, documented default that excludes an unreliable metric.
- **`backend/src/medrag/evaluation/`** — new package (`evaluation.py`, `__init__.py`), plus `run_evaluation.py`.

## Key Design Decisions

1. **A small (18-question), fully hand-verified test set over a larger LLM-generated one.** Every ground truth answer traces to real chunk content actually inspected during this project — no fabricated or LLM-generated ground truth. Initially built as 8 questions, then deliberately expanded to 18 for statistical reliability, including genuine PubMed coverage (added only after pulling and inspecting real PubMed chunk content first, rather than guessing at plausible-sounding PubMed facts).
2. **Deliberately includes 3 weak-coverage questions**, not just easy wins. An evaluation that only tests favorable cases isn't a real evaluation; these three (general blood sugar regulation, cardiac anatomy, inflammatory response mechanism) test whether the system honestly reports its real limitations rather than hallucinating, directly extending the qualitative finding from Phase 10's diagnostic query into a repeatable, quantitative test.
3. **Two model roles kept strictly separate and never confused.** The production generation model (`gpt-4.1-nano`, Phase 14) generates every answer being evaluated — the system under test never changes. The judge model (`gpt-5.2`) only scores those already-generated answers, a one-time, low-volume cost that's reasonable even though the same model would be too expensive for real per-query production use.
4. **`context_recall` is excluded from the default reported metrics**, based on a specific, reproduced investigation, not a vague suspicion. Full reasoning under Results below.
5. **Environment/dependency issues were resolved by root-causing each one specifically**, not by broad reinstalls or guesswork: an outdated `ragas` version, a confirmed upstream bug in a newer `ragas` version (worked around, not silently ignored), and a non-obvious internal `OPENAI_API_KEY` environment-variable requirement inside RAGAS's own embeddings client.

## Results

- **Reportable metrics** (`gpt-4.1-nano` generation, `gpt-5.2` judge, production script run): `faithfulness = 0.8637`, `answer_relevancy = 0.8383`, `context_precision = 0.7917`.
- **The three weak-coverage questions correctly scored poorly** across faithfulness/relevancy/precision in every evaluation run — direct, repeatable, quantitative confirmation that the system's honest "I don't have enough information" behavior (designed and validated qualitatively in Phase 14) holds up under formal evaluation, not just in a handful of manually-checked examples.
- **`context_recall` was investigated and found genuinely unreliable, not just imprecise — this is the phase's central methodological finding.** With `gpt-4.1-nano` as judge, it returned a flat `1.0` across every one of the 18 rows, including rows that scored `0` on every other metric simultaneously — a combination that cannot be genuinely correct. Switching to `gpt-5.2` as judge produced real variation, but a specific row (ACE inhibitor side effects) that was manually verified — by reading the full retrieved context directly — to contain every claim in its ground truth still scored `0.0`. Re-running that identical row three times, with unchanged input, produced `0.0`, `0.0`, then `1.0` — proving this is outright non-determinism on the exact same question, not measurement noise around a stable true value. `context_recall` is excluded from the default reported metric set as a result, with the full investigation documented in code and available via an explicit opt-in flag for anyone who wants to inspect it further.
- **A concrete, reproducible instance of the `gpt-4.1-nano` cost/quality tradeoff was found and directly confirmed**, not left as a theoretical caveat. One test question (bone-health/diabetes association) was answered incorrectly by the production model, despite the correct fact being clearly present, verified by direct inspection, in the retrieved context. Re-running the identical question with `gpt-5.2` correctly extracted the fact with a proper citation — the same retrieved context, a different outcome, isolating the failure to generation-model capacity rather than retrieval. This gives Phase 14's documented fallback plan (`gpt-5.2` for inadequate cases) real, demonstrated evidence rather than a hypothetical justification.
- **Run-to-run variance was observed even in the "reliable" metrics**: an earlier notebook run produced `faithfulness/answer_relevancy/context_precision` of `0.6866/0.7906/0.7738`, while the final production script run produced `0.8637/0.8383/0.7917` on the identical test set and pipeline. This is attributed to inherent LLM-as-judge non-determinism (the same underlying phenomenon behind the `context_recall` finding) and is documented as a general limitation of this evaluation approach — the reported numbers should be read as one representative sample from a noisy process, not an exact, reproducible ground truth.

## Challenges & Solutions

- **A chain of environment/dependency issues** (an outdated `ragas` incompatible with current `langchain-core`; a confirmed, currently-open upstream `ragas` bug importing a `ChatVertexAI` path that no longer exists in any current `langchain-community` release; a schema rename between `ragas` versions; RAGAS's internal embeddings client requiring an OS-level environment variable separate from this project's own settings mechanism) were each diagnosed to their specific root cause and fixed individually — including verifying the upstream bug was genuinely external to this project (via web research confirming other users hitting the identical error) rather than assuming a local misconfiguration.
- **A suspiciously perfect metric score was investigated rather than accepted.** A flat `1.0` `context_recall` across all 18 rows was recognized as implausible on its face (given simultaneous total failures on other metrics) and traced, through a deliberate three-step investigation (cross-judge comparison, manual ground-truth verification against retrieved text, and a repeated-run determinism check), to a genuine metric/judge reliability problem rather than either accepting the number at face value or dismissing the finding without proof.
- **A `KeyError` in the runner script's own result-serialization code** (unrelated to `ragas`'s upstream bug) was resolved by computing the aggregate scores from the per-question dataframe directly, avoiding a dependency on this `ragas` version's non-standard object-to-dict conversion behavior entirely.

## Files Created

- `backend/src/medrag/evaluation/__init__.py`
- `backend/src/medrag/evaluation/evaluation.py` (`apply_vertexai_stub`, `load_test_set`, `run_pipeline_on_test_set`, `run_ragas_evaluation`)
- `backend/scripts/run_evaluation.py` (`--generation-model`, `--judge-model`, `--include-unreliable-metrics` flags)
- `data/eval/ragas_test_set.json`
- `data/eval/results.json` (generated output — per-question and aggregate scores)
- `notebooks/phase17_ragas_evaluation.ipynb`