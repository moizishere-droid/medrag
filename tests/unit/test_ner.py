"""Unit tests for the medical NER helpers (Phase 12).

No scispaCy model is loaded for these tests: extract_medical_entities is driven
by a fake spaCy pipeline. The single real-model test at the bottom skips itself
automatically when en_ner_bc5cdr_md is not installed.
"""

from types import SimpleNamespace

import pytest

import medrag.ner.ner as ner
from medrag.ner.ner import DOSAGE_PATTERN, extract_medical_entities, is_likely_noise


# --------------------------------------------------------------------------
# is_likely_noise
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    [
        "NCT01234567",  # clinical trial id
        "nct01234567",  # case-insensitive
        "  NCT0123  ",  # surrounding whitespace is stripped
        "NOITACILBUP",  # mirrored PDF artifact: PUBLICATION reversed
        "HCRAESER",  # RESEARCH reversed
        "THGIRYPOC",  # COPYRIGHT reversed
        "DEVRESER",  # RESERVED reversed
        "noitacilbup",  # lowercase mirrored form
        "140",  # bare number misfired as CHEMICAL
        "140.5",
        " 7 ",
    ],
)
def test_known_noise_patterns_are_filtered(text):
    assert is_likely_noise(text) is True


@pytest.mark.parametrize(
    "text",
    [
        # Short abbreviations the module docstring says MUST survive the filter.
        "ARB",
        "ACEi",
        "CCB",
        "DM",
        "HTN",
        # Ordinary entities
        "metformin",
        "candesartan",
        "type 2 diabetes mellitus",
        # Near-misses of the noise patterns
        "publication",  # the real word; only the MIRRORED form is an artifact
        "NCT",  # no digits, so not a trial id
        "NCT123abc",
        "1.2.3",
    ],
)
def test_legitimate_entities_are_kept(text):
    assert is_likely_noise(text) is False


@pytest.mark.parametrize("text", ["HHS", "CIP", "A3.1"])
def test_known_unfiltered_misfires_are_an_accepted_limitation(text):
    """Characterization of a DOCUMENTED limitation: these front-matter misfires
    are deliberately not filtered, because any rule broad enough to catch them
    would also reject ARB/ACEi/CCB/DM/HTN. If this test starts failing, someone
    broadened the filter. Re-run the keep-list above before accepting that."""
    assert is_likely_noise(text) is False


# --------------------------------------------------------------------------
# DOSAGE_PATTERN
# --------------------------------------------------------------------------
def dosages(text):
    return [m.group() for m in DOSAGE_PATTERN.finditer(text)]


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Take 500 mg twice daily.", ["500 mg"]),
        ("500mg", ["500mg"]),  # no space
        ("0.5 mg/day", ["0.5 mg/day"]),
        ("10 mg/kg", ["10 mg/kg"]),
        ("2.5 mL", ["2.5 mL"]),
        ("5 mcg", ["5 mcg"]),
        ("100 IU", ["100 IU"]),
        ("40 units", ["40 units"]),
        ("1 unit", ["1 unit"]),
        ("500 MG", ["500 MG"]),  # case-insensitive
        ("5 mg or 10 mg", ["5 mg", "10 mg"]),
        ("Take it twice daily.", []),
        ("130/80 mmHg", []),  # blood pressure is not a dosage
        ("1 gram", []),  # 'g' must end at a word boundary
        ("", []),
    ],
)
def test_dosage_pattern(text, expected):
    assert dosages(text) == expected


@pytest.mark.xfail(
    strict=True,
    reason=(
        "False positives: lab/renal units are extracted as dosages ('126 mg', "
        "'60 mL', '13 g'), with the /dL or /min suffix dropped. Decide whether "
        "to exclude these units or document it as accepted, then flip the test."
    ),
)
@pytest.mark.parametrize(
    "text", ["Fasting glucose 126 mg/dL", "eGFR 60 mL/min", "Hemoglobin 13 g/dL"]
)
def test_lab_values_are_not_dosages(text):
    assert dosages(text) == []


# --------------------------------------------------------------------------
# extract_medical_entities (fake model)
# --------------------------------------------------------------------------
class FakeNlp:
    """Stands in for the spaCy pipeline: returns canned (text, label) entities."""

    def __init__(self, ents):
        self._ents = ents

    def __call__(self, text):
        return SimpleNamespace(
            ents=[SimpleNamespace(text=t, label_=label) for t, label in self._ents]
        )


@pytest.fixture
def install_fake_model(monkeypatch):
    def _install(ents):
        monkeypatch.setattr(ner, "get_ner_model", lambda: FakeNlp(ents))

    return _install


def test_entities_are_routed_by_label_and_other_labels_ignored(install_fake_model):
    install_fake_model(
        [("metformin", "CHEMICAL"), ("diabetes", "DISEASE"), ("BRCA1", "GENE")]
    )
    out = extract_medical_entities("irrelevant")
    assert out == {"chemicals": ["metformin"], "diseases": ["diabetes"], "dosages": []}


def test_dosages_come_from_regex_not_from_the_model(install_fake_model):
    install_fake_model([])
    out = extract_medical_entities("Give 500 mg then 250 mg.")
    assert out["dosages"] == ["500 mg", "250 mg"]
    assert out["chemicals"] == [] and out["diseases"] == []


def test_noise_is_filtered_from_chemicals_and_diseases_by_default(install_fake_model):
    install_fake_model(
        [
            ("metformin", "CHEMICAL"),
            ("NCT01234567", "CHEMICAL"),
            ("140", "CHEMICAL"),
            ("hypertension", "DISEASE"),
            ("NOITACILBUP", "DISEASE"),
        ]
    )
    out = extract_medical_entities("irrelevant")
    assert out["chemicals"] == ["metformin"]
    assert out["diseases"] == ["hypertension"]


def test_filter_noise_false_returns_raw_model_output(install_fake_model):
    install_fake_model([("NCT01234567", "CHEMICAL"), ("NOITACILBUP", "DISEASE")])
    out = extract_medical_entities("irrelevant", filter_noise=False)
    assert out["chemicals"] == ["NCT01234567"]
    assert out["diseases"] == ["NOITACILBUP"]


def test_dosages_are_never_noise_filtered(install_fake_model):
    install_fake_model([])
    assert extract_medical_entities("5 mg", filter_noise=True)["dosages"] == ["5 mg"]


# --------------------------------------------------------------------------
# get_ner_model caching
# --------------------------------------------------------------------------
def test_model_is_loaded_once_and_cached(monkeypatch):
    loads = []
    monkeypatch.setattr(ner, "_nlp_cache", None)
    monkeypatch.setattr(ner.spacy, "load", lambda name: loads.append(name) or object())

    first = ner.get_ner_model()
    second = ner.get_ner_model()

    assert first is second
    assert loads == ["en_ner_bc5cdr_md"]


# --------------------------------------------------------------------------
# Real model (skipped when the scispaCy model is not installed)
# --------------------------------------------------------------------------
def test_real_model_extracts_a_drug_a_disease_and_a_dosage():
    pytest.importorskip("en_ner_bc5cdr_md")
    out = extract_medical_entities("Lisinopril is used to treat hypertension. Dose: 10 mg daily.")
    assert "lisinopril" in [c.lower() for c in out["chemicals"]]
    assert "hypertension" in [d.lower() for d in out["diseases"]]
    assert out["dosages"] == ["10 mg"]
