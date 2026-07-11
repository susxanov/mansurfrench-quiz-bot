import hashlib
import re
from schemas import CandidateQuestion
from text_utils import clean_quiz_prompt, normalize_text

FORBIDDEN = ("🇷🇺", "🇫🇷", "Exercice ", "Exercise ", "Упражнение ")


def canonical_prompt(value: str) -> str:
    return normalize_text(clean_quiz_prompt(value))


def fingerprint(item: CandidateQuestion) -> str:
    options = "|".join(sorted(normalize_text(x) for x in item.options))
    body = canonical_prompt(item.prompt) + "|" + options
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def validate_question(item: CandidateQuestion, expected_level: str, expected_type: str) -> list[str]:
    errors: list[str] = []
    original_prompt = item.prompt
    item.prompt = clean_quiz_prompt(item.prompt)
    if original_prompt != item.prompt:
        errors.append("internal_or_forbidden_text")
    if item.level != expected_level:
        errors.append("wrong_level")
    if item.question_type != expected_type:
        errors.append("wrong_question_type")
    combined = " ".join([item.prompt, *item.options, item.explanation])
    if any(marker.lower() in combined.lower() for marker in FORBIDDEN):
        errors.append("internal_or_forbidden_text")
    if len(set(item.options)) != 4:
        errors.append("duplicate_options")
    if not 0 <= item.correct_option_id <= 3:
        errors.append("invalid_correct_option")
    if len(item.explanation) > 190:
        errors.append("explanation_too_long")
    if expected_type == "translation" and not re.search(r"[А-Яа-яЁё]", item.prompt):
        errors.append("translation_prompt_must_be_russian")
    if expected_type == "conjugation" and not any(
        token in item.prompt.lower()
        for token in ("conjug", "forme", "choisissez", "complétez", "спряж")
    ):
        errors.append("conjugation_prompt_unclear")
    return errors
