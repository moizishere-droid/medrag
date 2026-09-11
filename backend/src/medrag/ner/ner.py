"""
Medical Named Entity Recognition: extracts CHEMICAL (drug) and DISEASE
entities from text via scispaCy's en_ner_bc5cdr_md model, plus dosage
mentions via a supplementary regex pass.

Model choice: en_ner_bc5cdr_md over en_core_sci_md. The latter was
tested and rejected - it only exposes a single generic 'ENTITY' label
(no CHEMICAL/DISEASE distinction) and extracted substantial noise on
real WHO guideline text (generic words like 'patients', 'daily', 'dose'
tagged as entities). en_ner_bc5cdr_md, trained specifically on the
BC5CDR chemical+disease corpus, gave precise, correctly-labeled
extractions with no equivalent noise on the same test text.

Dosage extraction is regex-based, not model-based: bc5cdr was never
trained to recognize dosage patterns (it only has CHEMICAL/DISEASE
labels), and dosage numbers are a well-defined pattern that doesn't
need a trained model.

Known, documented limitation (not fixed here - see is_likely_noise()):
bc5cdr occasionally misfires on document front-matter (title pages,
license/copyright text, tables of contents, acknowledgements) - e.g.
tagging 'HHS' or a section reference like 'A3.1' as a DISEASE. This was
investigated directly: a corpus-wide frequency-based filter was tested
and found to NOT work, since genuine rare drug names (e.g.
'candesartan', mentioned once in a whole guideline) sit at the exact
same low frequency as genuine noise tokens. A broader token-shape
filter (e.g. rejecting short all-caps tokens) was also rejected, since
it would equally reject legitimate short medical abbreviations that
must be kept (ARB, ACEi, CCB, DM, HTN). Only concrete, narrowly-scoped
noise patterns are filtered here; short ambiguous misfires remain a
known, accepted limitation.
"""

import logging
import re
from typing import Dict, List

import spacy

logger = logging.getLogger("medrag.ner")

NER_MODEL_NAME = "en_ner_bc5cdr_md"

DOSAGE_PATTERN = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:mg|mcg|g|ml|mL|IU|units?)\b(?:/(?:day|dose|kg|mL))?",
    re.IGNORECASE,
)
TRIAL_ID_PATTERN = re.compile(r"^NCT\d+$", re.IGNORECASE)
_REVERSED_ARTIFACT_WORDS = {"publication", "research", "copyright", "reserved"}

_nlp_cache = None


def get_ner_model():
    """Cached scispaCy bc5cdr model - loading has real startup cost, so
    it's loaded once per process rather than per call."""
    global _nlp_cache
    if _nlp_cache is None:
        logger.info(f"Loading NER model '{NER_MODEL_NAME}'...")
        _nlp_cache = spacy.load(NER_MODEL_NAME)
    return _nlp_cache


def is_likely_noise(entity_text: str) -> bool:
    """Filter concrete, directly-observed noise patterns only:
    clinical trial IDs (NCT########), reversed-text PDF extraction
    artifacts (e.g. 'NOITACILBUP' from mirrored/rotated page elements),
    and bare numeric tokens misfired as CHEMICAL (e.g. a lab value like
    '140'). Deliberately narrow - does not attempt to catch short
    ambiguous abbreviation misfires (e.g. 'HHS', 'CIP'), since a filter
    broad enough to catch those would also reject legitimate short
    medical abbreviations (ARB, ACEi, CCB, DM, HTN) that must be kept."""
    text = entity_text.strip()

    if TRIAL_ID_PATTERN.match(text):
        return True
    if text[::-1].lower() in _REVERSED_ARTIFACT_WORDS:
        return True
    if re.fullmatch(r"\d+(\.\d+)?", text):
        return True

    return False


def extract_medical_entities(text: str, filter_noise: bool = True) -> Dict[str, List[str]]:
    """Extract chemicals, diseases, and dosages from text.

    chemicals/diseases come from the bc5cdr NER model; dosages come from
    a separate regex pass. filter_noise=True (default) drops entities
    matching is_likely_noise() before returning - set False to inspect
    raw, unfiltered model output (e.g. for debugging or re-evaluating
    the noise filter itself)."""
    nlp = get_ner_model()
    doc = nlp(text)

    chemicals = [ent.text for ent in doc.ents if ent.label_ == "CHEMICAL"]
    diseases = [ent.text for ent in doc.ents if ent.label_ == "DISEASE"]
    dosages = [m.group() for m in DOSAGE_PATTERN.finditer(text)]

    if filter_noise:
        chemicals = [e for e in chemicals if not is_likely_noise(e)]
        diseases = [e for e in diseases if not is_likely_noise(e)]

    return {"chemicals": chemicals, "diseases": diseases, "dosages": dosages}