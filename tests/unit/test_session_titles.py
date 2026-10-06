import pytest
from medrag.memory.chat_memory import title_from_query


@pytest.mark.parametrize("query,title", [
    ("What is diabetes?", "Diabetes"),
    ("What is type 2 diabetes?", "Diabetes Type 2"),
    ("Please tell me about diabetes type 2", "Diabetes Type 2"),
    ("What are the symptoms of diabetes?", "Diabetes"),
    ("Explain HIV", "HIV"),
    ("  ", "New Chat"),
])
def test_topic_titles(query, title):
    assert title_from_query(query) == title


def test_title_is_bounded():
    assert len(title_from_query("word " * 50).split()) == 8
    assert len(title_from_query("a" * 200)) == 80
