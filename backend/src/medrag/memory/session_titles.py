"""Lightweight topic labels shared by the API and frontend."""
import re


def title_from_query(query: str) -> str:
    """A short deterministic topic title, with no additional model request."""
    text = re.split(r"[?!.](?:\s|$)", " ".join(query.strip().split()), maxsplit=1)[0].rstrip("?!. ")
    text = re.sub(r"^(?:please\s+)?(?:can you\s+|could you\s+)?(?:tell me about\s+|explain\s+|describe\s+|what (?:is|are)\s+)", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^(?:the\s+)?(?:symptoms|causes|treatment|management|definition)\s+(?:of|for)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\btype\s*([12])\s+diabetes\b", r"diabetes type \1", text, flags=re.IGNORECASE)
    words = text.split()[:8]
    title = " ".join(word if word.isupper() and len(word) <= 6 else word.capitalize() for word in words)
    return title[:80].rstrip() or "New Chat"
