import hashlib
import re
from collections.abc import Iterable

from schemas import CandidateQuestion
from text_utils import clean_quiz_prompt, normalize_text

FORBIDDEN_MARKERS = (
    "🇷🇺",
    "🇫🇷",
    "exercice ",
    "exercise ",
    "упражнение ",
)

_WORD_RE = re.compile(r"[a-zà-ÿа-яё0-9']+", re.IGNORECASE)


def canonical_prompt(value: str) -> str:
    return normalize_text(clean_quiz_prompt(value))


def prompt_tokens(value: str) -> set[str]:
    return set(_WORD_RE.findall(canonical_prompt(value)))


def prompts_too_similar(first: str, second: str, threshold: float = 0.78) -> bool:
    a = prompt_tokens(first)
    b = prompt_tokens(second)
    if not a or not b:
        return False
    return len(a & b) / len(a | b) >= threshold


def is_duplicate_or_similar(prompt: str, existing_prompts: Iterable[str]) -> bool:
    key = canonical_prompt(prompt)
    for previous in existing_prompts:
        if key == canonical_prompt(previous) or prompts_too_similar(prompt, previous):
            return True
    return False


def fingerprint(item: CandidateQuestion) -> str:
    # Option order is ignored, so shuffling cannot bypass duplicate detection.
    options = "|".join(sorted(normalize_text(option) for option in item.options))
    body = canonical_prompt(item.prompt) + "|" + options
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def validate_question(
    item: CandidateQuestion,
    expected_level: str,
    expected_type: str,
    raw_prompt: str | None = None,
) -> list[str]:
    errors: list[str] = []
    original_prompt = raw_prompt if raw_prompt is not None else item.prompt
    cleaned_prompt = clean_quiz_prompt(original_prompt)
    item.prompt = cleaned_prompt

    if cleaned_prompt != str(original_prompt).strip():
        errors.append("internal_prefix")
    if item.level != expected_level:
        errors.append("wrong_level")
    if item.question_type != expected_type:
        errors.append("wrong_question_type")

    combined = " ".join([item.prompt, *item.options, item.explanation]).lower()
    if any(marker in combined for marker in FORBIDDEN_MARKERS):
        errors.append("forbidden_text")
    if len(set(item.options)) != 4:
        errors.append("duplicate_options")
    if len(item.explanation) > 190:
        errors.append("explanation_too_long")
    if not re.search(r"[А-Яа-яЁё]", item.explanation):
        errors.append("explanation_must_be_russian")

    if expected_type == "translation":
        if not re.search(r"[А-Яа-яЁё]", item.prompt):
            errors.append("translation_prompt_must_be_russian")
        if not all(re.search(r"[A-Za-zÀ-ÿ]", option) for option in item.options):
            errors.append("translation_options_must_be_french")

    if expected_type == "conjugation":
        prompt = item.prompt.lower()
        if not any(
            marker in prompt
            for marker in ("choisissez", "complétez", "quelle forme", "спряж", "выберите")
        ):
            errors.append("conjugation_prompt_unclear")

    return errors
