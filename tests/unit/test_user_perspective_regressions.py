"""Regression cases found during the six-query user-perspective review."""
from pathlib import Path
from types import SimpleNamespace
import importlib
import pytest
from medrag.generation.generation import format_context
from medrag.generation.language import AnswerLanguageError, complete_in_query_language, answer_preserves_topic
from medrag.citations.visuals import VisualCatalog
from medrag.citations.citations import get_who_source_url
from medrag.memory.session_titles import title_from_query


def test_corrupt_pdf_tokens_never_reach_generation_context(tmp_path):
    results=[{"payload":{"source":"who","source_id":"hypertension","chunk_id":"c","raw_text":"Threshold (cid:562) (cid:20)"}}]
    context=format_context(results,visual_catalog=VisualCatalog(tmp_path))
    assert "(cid:" not in context and "not usable evidence" in context


def test_actual_diagram_heading_does_not_expose_flattened_clinical_cells():
    results=[{"payload":{"source":"who","source_id":"dengue fever","chunk_id":"c",
                          "raw_text":"Dengue case classification by severity\nWarning signs\nMucosal bleed\n3."}}]
    context=format_context(results)
    assert "Verified figure caption" in context
    assert "Mucosal bleed" not in context
    assert "Do not infer diagnostic details" in context


def test_corrupt_candidates_cannot_displace_clean_evidence(monkeypatch):
    mod=importlib.import_module("medrag.retrieval.reranking")
    pairs=[]
    def predict(values):pairs.extend(values);return [1.0]*len(values)
    monkeypatch.setattr(mod,"get_cross_encoder",lambda:SimpleNamespace(predict=predict))
    bad={"payload":{"raw_text":"(cid:3) 140"}}
    good={"payload":{"raw_text":"Readable evidence"}}
    assert mod.rerank("question",[bad,good])==[good]
    assert pairs==[("question","Readable evidence")]


def test_urdu_blood_pressure_mistranslation_is_rejected_and_repaired():
    query="ہائی بلڈ پریشر کیا ہے؟ آسان اردو میں سمجھائیں۔"
    bad="ہائی بلڈ پریشر، یا آنکھوں کا دباؤ زیادہ ہونا، ایک حالت ہے۔"
    good="ہائی بلڈ پریشر خون کی نالیوں میں دباؤ بڑھنے کو کہتے ہیں [1]۔"
    assert not answer_preserves_topic(bad,query)
    calls=[];replies=iter([bad,good])
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=next(replies)))])
    client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    assert complete_in_query_language(client,"model",[{"role":"system","content":"Evidence"}],query)==good
    assert len(calls)==2 and calls[0]["max_completion_tokens"]==1000
    assert answer_preserves_topic("Eye pressure is a different concept.","How does hypertension affect eye pressure?")


@pytest.mark.parametrize("answer,reason",[("","stop"),("Partial medical answer","length")])
def test_empty_or_truncated_completions_are_not_published(answer,reason):
    def create(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=answer),finish_reason=reason)])
    client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with pytest.raises(AnswerLanguageError):complete_in_query_language(client,"model",[{"role":"system","content":"Evidence"}],"What is hypertension?")


def test_who_filename_slugs_resolve_source_urls():
    assert get_who_source_url("dengue fever",{"dengue_fever":"https://who.int/dengue"})=="https://who.int/dengue"
    assert title_from_query("What is hypertension? Explain simply and cite the sources.")=="Hypertension"
