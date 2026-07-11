import re
import unicodedata
from typing import Any

_INTERNAL_PREFIX = re.compile(
    r"^\s*(?:(?:exercice|exercise|упражнение)\s+[^\s:,.!?]+\s*[.:—-]?\s*)+",
    re.IGNORECASE,
)


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().lower()
    return re.sub(r"\s+", " ", text)


def clean_quiz_prompt(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    previous = None
    while text != previous:
        previous = text
        text = _INTERNAL_PREFIX.sub("", text).strip()
    return text


def clip_explanation(value: Any, limit: int = 190) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-.")
    return cut + "."
