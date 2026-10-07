# Response-time improvements — 7 October 2026

CPU cross-encoder reranking was the largest measured local delay. The optimized
path runs the same model in FP32 ONNX Runtime. Tokenization, truncation, activation,
candidate count (20), final result count (5), source filters and citation numbering
are preserved. No quantization, shorter text limits, smaller candidate pool or
shared query/evidence cache was adopted. The quantization trial offered little
speed improvement and changed one top-five set, so it was rejected.

| Live question | Original pipeline | Optimized pipeline | Reduction |
|---|---:|---:|---:|
| What is type 2 diabetes? | 15.968 s | 5.343 s | 66.5% |
| What is hypertension? | 13.492 s | 5.820 s | 56.9% |
| What is metformin used for? | 9.105 s | 4.571 s | 49.8% |

All three comparisons returned exactly the same ordered top-five chunk IDs.
The earlier same-input reranking microbenchmark measured 6.7–9.8 seconds with
PyTorch versus 1.9–4.0 seconds with ONNX, with maximum score difference below
0.000007. This comparison is evidence of numerical agreement on the tested
samples; it is not a new clinical-quality evaluation.

The live benchmark includes query embedding, hybrid search, reranking, graph
lookup, live answer generation, language validation and PostgreSQL message
storage. Startup/export, browser rendering, HTTP route overhead and citation
resolution are excluded. Both modes were warmed first. Questions were neutral
test prompts, with newly created sessions in `medrag_chat_test`, deleted after
the run. Qdrant and Neo4j were read-only. Answers were not saved in the benchmark
artifact, only lengths, timings and retrieved chunk IDs. Raw measurements are
in `performance_benchmark.json`. Model answer lengths differ between runs; these
are paired samples, not a statistically controlled response-time guarantee.

The final export wiring was checked with an explicit regression test after the
full-pipeline comparison caught a mask/segment input-order error. The corrected
cache format is v2. The initial rejected comparison was replaced by the valid
measurements above. `benchmark_chat_latency.py --live` explicitly opts into paid
embedding/generation calls and checks evidence equality before saving results.

Clearly standalone English definition questions naming a configured topic now
skip the unnecessary history-rewrite model request, while still including
history in answer generation. Questions containing contextual references, such
as "What are its contraindications?", retain rewriting. Ambiguous and other
queries conservatively retain the existing behavior.

Verification: 300 unit/API/frontend tests passed; the full 50-test integration
suite passed before the final export correction. The corrected export passed
its real ONNX regression test and live score/evidence comparison; affected real
startup, PostgreSQL and Qdrant checks were subsequently rerun: all 28 passed. Existing retrieval
privacy filters and upload-isolation tests are unchanged.

## Activation and practical limits

Install the updated requirements and restart the backend once. The default CPU
runtime is `RERANK_BACKEND=onnx` with `RERANK_THREADS=4`. Set the backend to
`torch` to revert. The initial ONNX export takes additional startup time and uses
about 91 MB of disk; `.medrag_cache/` is ignored by Git. File locking and atomic
replacement protect exports when workers start together, and weights/configuration
identify the cached model. Model export files contain weights, not user data.
GPU installations retain the existing PyTorch path.

The reported 32–45 seconds was not reproduced by these neutral warmed prompts.
Long answers, network/provider retries, language correction retries, startup and
concurrent load can still add latency. The measured improvement is real, but five
seconds is not promised for every query. Benchmark the deployment hardware and
concurrent requests before setting a response-time target.
