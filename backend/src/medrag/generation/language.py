"""Choose response language from the current question, independent of history."""
import logging
import re
import unicodedata

from langdetect import DetectorFactory
from langdetect.lang_detect_exception import LangDetectException
from langdetect.detector_factory import PROFILES_DIRECTORY

from medrag.generation.limits import MAX_ANSWER_TOKENS

logger = logging.getLogger("medrag.generation")
_factory = DetectorFactory()
_factory.seed = 0
_factory.load_profile(PROFILES_DIRECTORY)
LANGUAGE_NAMES = {"en": "English", "ur": "Urdu", "ur-Latn": "Roman Urdu (Urdu written in the Latin alphabet)",
                  "hi": "Hindi", "ar": "Arabic", "ru": "Russian", "es": "Spanish", "fr": "French",
                  "de": "German", "pt": "Portuguese", "it": "Italian", "zh-cn": "Simplified Chinese",
                  "zh-tw": "Traditional Chinese", "ja": "Japanese", "ko": "Korean", "bn": "Bengali"}


class AnswerLanguageError(RuntimeError):
    pass


def probabilities(text):
    try:
        detector = _factory.create()
        detector.append(text)
        return detector.get_probabilities()
    except LangDetectException:
        return []


def detect_query_language(query):
    words = set(re.findall(r"[a-z]+", query.lower()))
    letters = [c for c in query if c.isalpha()]
    latin = sum("LATIN" in unicodedata.name(c, "") for c in letters)
    mostly_latin = bool(letters) and latin / len(letters) > 0.9
    if mostly_latin:
        # Statistical detection can confidently mistake shared medical terms
        # (e.g. "diabetes") for another Romance language on a short question.
        if "¿" in query or re.search(r"\b(?:qué|que|cómo|como)\s+(?:es|son|se|puedo)\b", query, re.I):
            return "es"
        roman_urdu = {"kya", "hai", "hain", "hoti", "hota", "mujhe", "batao", "samjhao", "matlab"}
        if len(words & roman_urdu) >= 2:
            return "ur-Latn"
        # Short medical follow-ups are unreliable statistical samples. English
        # question grammar takes precedence over a foreign-looking drug name.
        english = {"what", "why", "how", "when", "where", "which", "does", "means", "mean", "its", "is", "are", "the"}
        if len(words & english) >= 2 or re.match(r"\s*(what|why|how|explain|describe|tell me)\b", query, re.I):
            return "en"
        if len(words) <= 1:
            return "en"  # ambiguous standalone medical terms default to English
    guesses = probabilities(query)
    return guesses[0].lang if guesses and guesses[0].prob >= 0.8 else "en"


def language_instruction(query):
    code = detect_query_language(query)
    name = LANGUAGE_NAMES.get(code, f"the language with ISO code {code}")
    return (f"\n\nResponse language for THIS turn: {name}. Respond exclusively in {name}. "
            "The latest original user question determines the language. Earlier assistant replies, "
            "retrieval rewrites and source documents must not change it. Preserve medical terms and citation markers.")


def answer_matches_language(answer, target):
    text = re.sub(r"https?://\S+|\[\d+\]", "", answer or "")
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return True
    latin_ratio = sum("LATIN" in unicodedata.name(c, "") for c in letters) / len(letters)
    if target in {"en", "ur-Latn"} and latin_ratio < 0.85:
        return False
    if target == "ur-Latn" or len(letters) < 50:
        return True
    guesses = probabilities(text)
    if not guesses or guesses[0].prob < 0.95:
        return True  # do not reject an ambiguous short/technical answer
    expected = target.split("-")[0]
    return guesses[0].lang.split("-")[0] == expected


def answer_preserves_topic(answer, query):
    """Block the reproduced blood-pressure/eye-pressure mistranslation."""
    blood_pressure = re.search(r"hypertension|high blood pressure|بلڈ پریشر|خون کا دباؤ", query, re.I)
    eyes_requested = re.search(r"eye|ocular|glaucoma|آنکھ", query, re.I)
    eye_pressure = re.search(r"eye pressure|intraocular pressure|آنکھ(?:وں)? کا دبا[ؤو]", answer or "", re.I)
    return not (blood_pressure and not eyes_requested and eye_pressure)


def complete_in_query_language(client, model, messages, query):
    target = detect_query_language(query)
    for attempt in range(2):
        response = client.chat.completions.create(model=model, messages=messages, max_completion_tokens=MAX_ANSWER_TOKENS)
        if not response.choices or getattr(response.choices[0], "finish_reason", None) == "length":
            raise AnswerLanguageError("The answer exceeded its response limit. Please ask a narrower question.")
        answer = response.choices[0].message.content
        if not answer or not answer.strip():
            raise AnswerLanguageError("The answer service returned an empty response. Please retry.")
        if answer_matches_language(answer, target) and answer_preserves_topic(answer, query):
            return answer
        logger.warning("Answer language mismatch; target=%s attempt=%s", target, attempt + 1)
        messages = [dict(message) for message in messages]
        messages[0]["content"] += language_instruction(query) + " A previous attempt used another language or confused medical concepts. Correct that error using only the supplied evidence. Blood pressure and eye pressure are different concepts."
    raise AnswerLanguageError("The model could not produce a consistent answer in the question's language. Please retry.")
