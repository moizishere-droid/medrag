from types import SimpleNamespace
import pytest
from medrag.generation.language import (
    AnswerLanguageError, detect_query_language, language_instruction,
    complete_in_query_language,
)


@pytest.mark.parametrize("query,code", [
    ("antihypertensive what its means?", "en"),
    ("What is hypertension?", "en"),
    ("metformin", "en"),
    ("ذیابیطس کیا ہے؟", "ur"),
    ("diabetes kya hoti hai?", "ur-Latn"),
    ("¿Qué es la diabetes?", "es"),
    ("Что такое гипертония?", "ru"),
    ("Qu’est-ce que le diabète?", "fr"),
    ("मधुमेह क्या है?", "hi"),
    ("ما هو مرض السكري؟", "ar"),
    ("", "en"),
])
def test_detects_language_of_current_query(query, code):
    assert detect_query_language(query) == code
    assert detect_query_language(query) == code


def client_with_answers(*answers):
    calls = []
    replies = iter(answers)
    def create(model, messages):
        calls.append(messages)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=next(replies)))])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), calls


def test_wrong_language_is_regenerated_without_returning_it():
    client, calls = client_with_answers("Антигипертензивное средство снижает давление [1].", "An antihypertensive lowers blood pressure [1].")
    query = "antihypertensive what its means?"
    messages = [{"role": "system", "content": language_instruction(query)},
                {"role": "assistant", "content": "Русский предыдущий ответ."},
                {"role": "user", "content": query}]
    assert complete_in_query_language(client, "model", messages, query) == "An antihypertensive lowers blood pressure [1]."
    assert len(calls) == 2
    assert "Respond exclusively in English" in calls[0][0]["content"]
    assert "Correct that error" in calls[1][0]["content"]
    assert "Correct that error" not in messages[0]["content"]


def test_persistent_language_mismatch_is_not_published():
    client, calls = client_with_answers("Это лекарство [1].", "Это лекарство [1].")
    with pytest.raises(AnswerLanguageError):
        complete_in_query_language(client, "model", [{"role": "system", "content": "Evidence"}], "What is this medicine?")
    assert len(calls) == 2
