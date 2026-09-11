# Phase 12: Medical NER (spaCy + scispaCy) — Report

## Phase Objective

Extract structured medical entities — drugs/chemicals, diseases, and dosages — from chunk text, turning unstructured prose into queryable facts. This lays the groundwork for Phase 14's knowledge graph (drug-disease relationship nodes require knowing which text spans actually name drugs and which name diseases) and for future entity-aware retrieval/citation.

## What Was Built

- **Model comparison** — tested `en_core_sci_md` against `en_ner_bc5cdr_md` (both scispaCy models) directly on real text before committing to one.
- **`get_ner_model()`** — cached loader for the chosen model, `en_ner_bc5cdr_md`.
- **`extract_medical_entities()`** — combines bc5cdr's `CHEMICAL`/`DISEASE` NER output with a supplementary regex pass for dosage mentions (e.g. `500mg`), plus optional noise filtering.
- **`is_likely_noise()`** — a narrow, pattern-based filter for concrete, directly-observed extraction errors.
- **`backend/src/medrag/ner/`** — new package (`ner.py` + `__init__.py`).

## Key Design Decisions

1. **`en_ner_bc5cdr_md` over `en_core_sci_md`**, decided by direct comparison on real text rather than assumption. `en_core_sci_md` exposes only a single generic `ENTITY` label (no type distinction at all) and extracted substantial noise on a test passage — generic words (`patients`, `daily`, `dose`) tagged as entities, and malformed/truncated spans. `en_ner_bc5cdr_md`, trained specifically on the BC5CDR chemical+disease corpus, produced precise, correctly-labeled, immediately usable output on the identical test text, with the exact two entity types (`CHEMICAL`, `DISEASE`) Phase 14's graph needs.
2. **Dosage extraction via regex, not the NER model.** `bc5cdr` was never trained to recognize dosage patterns — it only has two labels. Dosage mentions (`500mg`, `2.5mg/day`) are a well-defined numeric pattern that a trained model isn't needed for; a lightweight regex pass runs alongside the NER call instead.
3. **Corpus-wide frequency filtering tested and rejected as a noise-reduction strategy.** Extraction was run across the full hypertension topic (146 chunks) specifically to test whether low-frequency entities could be filtered out as likely noise. This was disproven with real data: genuine, correct, rare drug names (e.g. `candesartan`, `olmesartan`, `methyldopa` — each mentioned only once in the guideline) sit at the exact same occurrence frequency as genuine noise tokens (`CIP`, `Q9`, a clinical trial ID). No single frequency threshold can separate the two.
4. **A narrow, concrete-pattern noise filter over a broad heuristic.** Rather than a token-shape filter (e.g. rejecting short all-caps tokens), which would also reject legitimate short medical abbreviations that must be kept (`ARB`, `ACEi`, `CCB`, `DM`, `HTN`), `is_likely_noise()` only catches three specific, directly-observed patterns: clinical trial IDs (`NCT\d+`), reversed-text PDF extraction artifacts, and bare numeric tokens misfired as `CHEMICAL`. This mirrors the project's established preference (seen in Phase 5's rejection of section-header chunking, and Phase 7's narrowly-scoped ToC-chunk filter) for filters that fix a confirmed, specific problem rather than guessing at a broader rule that risks new false negatives.
5. **The remaining noise gap is documented as an accepted limitation, not force-fixed.** Short, ambiguous misfires (`HHS`, `CIP`, `Q9`, tagged incorrectly in document front-matter like title pages and acknowledgements sections) are not caught by the current filter. Building a filter aggressive enough to catch these would also strip legitimate short abbreviations the system needs to keep. This tradeoff is stated plainly rather than hidden, consistent with the project's stated principle (first established with the WHO 12-topic coverage gap) of surfacing real limitations honestly rather than engineering around them at the risk of new errors.

## Results

- **Model comparison confirmed decisively**: on identical test text, `en_core_sci_md` produced 13 unlabeled spans including clear non-entities (`'patients'`, `'daily'`, `'dose'`, `'increased'`) and a malformed truncated span; `en_ner_bc5cdr_md` produced 6 correctly-labeled entities with zero noise on the same text.
- **Clean extraction confirmed on real clinical content**: spot-checked WHO hypertension chunks past the document's front matter correctly extracted `diabetes`, `coronary artery disease`, `stroke`, `myocardial infarction`, `heart failure`, and correctly recognized medical abbreviations (`HTN`, `DM`, `CAD`) as valid disease mentions; two chunks discussing only methodology correctly extracted zero entities rather than forcing false matches.
- **Front-matter noise confirmed and isolated**: extraction on the document's first several chunks (title page, license/copyright boilerplate, table of contents, acknowledgements) produced clear misfires (`CC`, `CIP` as `CHEMICAL`; `damages`, `A3.1`, `HHS` as `DISEASE`) — traced specifically to non-clinical boilerplate text, not a general model failure.
- **Frequency-filtering test (146 real chunks)**: of 106 unique chemicals extracted, singleton-frequency entities included both genuine drugs (`candesartan`, `Ramipril`, `hydralazine`, `spironolactone`, etc.) and genuine noise (`CIP`, `Q9`, `NCT04366050`) at identical frequency — confirming frequency alone is not a viable noise signal. Also surfaced an unrelated data-quality finding: reversed/mirrored text artifacts (`NOITACILBUP`, `HCRAESER` — "PUBLICATION"/"RESEARCH" spelled backwards), likely from a rare PDF rendering artifact in Phase 4 extraction, not an NER issue.
- **Final narrow filter verified**: removed exactly the 4 concrete noise items found in the frequency test (`140`, `NCT04366050`, `NOITACILBUP`, `HCRAESER`) while preserving all 102 remaining genuine chemical entities untouched, including every rare real drug name.
- **Production `extract_medical_entities()` verified to exactly reproduce notebook output** on the original test passage.

## Challenges & Solutions

- **scispaCy model download URLs from initial guidance were stale (404 errors).** Resolved by having the user retrieve the current URLs directly from the scispaCy GitHub README's model table — confirmed the correct S3 bucket path had changed (`ai2-s2-scispacy/releases/v0.5.4/`, not the previously assumed path).
- **Initial hypothesis (corpus-wide frequency filtering) was tested and proven wrong before being adopted**, rather than assumed to work and shipped. This is treated as a successful outcome of the phase's methodology, not a failure — the wrong approach was caught with real data before it reached production code, and the investigation directly informed the correct, narrower fix that was actually built.

## Files Created

- `backend/src/medrag/ner/__init__.py`
- `backend/src/medrag/ner/ner.py` (`get_ner_model`, `is_likely_noise`, `extract_medical_entities`)
- `notebooks/phase12_medical_ner.ipynb`

No new runner script — entity extraction is a function library, invoked per-chunk when needed (e.g. during Phase 14's knowledge graph construction), not a standalone batch job in this phase.