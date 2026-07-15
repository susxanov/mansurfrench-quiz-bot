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


_BLANK_RE = re.compile(r"_{3,}|\[?\]|…{2,}|\.\.\.")
_DOUBLE_CLITIC_PATTERNS = (
    re.compile(r"\b(?:je|tu|il|elle|on|nous|vous|ils|elles)\s+te\s+t[’']", re.I),
    re.compile(r"\b(?:je|tu|il|elle|on|nous|vous|ils|elles)\s+me\s+m[’']", re.I),
    re.compile(r"\b(?:je|tu|il|elle|on|nous|vous|ils|elles)\s+se\s+s[’']", re.I),
    re.compile(r"\blui\s+lui\b", re.I),
    re.compile(r"\bleur\s+leur\b", re.I),
    re.compile(r"\ben\s+en\b", re.I),
    re.compile(r"\by\s+y\b", re.I),
    re.compile(r"\b(?:le|la|les)\s+(?:le|la|les)\b", re.I),
    re.compile(r"[’']\s*[’']"),
)

def has_blank(value: str) -> bool:
    return bool(_BLANK_RE.search(value or ""))

def assemble_blank_variants(prompt: str, options: list[str]) -> list[str]:
    match = _BLANK_RE.search(prompt or "")
    if not match:
        return []
    before, after = prompt[:match.start()], prompt[match.end():]
    return [f"{before}{option}{after}" for option in options]

_ARTICLE_OPTIONS = {
    "au", "aux", "du", "des", "de", "d’", "d'", "de la", "de l’", "de l'",
    "le", "la", "les", "un", "une"
}
_CONTRACTED_ARTICLES = {"au", "aux", "du", "des"}
_DE_FORMS = {"de", "d’", "d'"}
_PRONOUN_OPTIONS = {
    "le", "la", "les", "lui", "leur", "en", "y", "qui", "que", "où", "dont",
    "me", "m’", "m'", "te", "t’", "t'", "se", "s’", "s'", "nous", "vous"
}
_QUANTITY_MARKERS = (
    "beaucoup", "peu", "assez", "trop", "combien", "plus de", "moins de",
    "un kilo", "une bouteille", "un verre", "une tranche", "une dizaine"
)
_NEGATION_MARKERS = (" ne ", " n’", " n'")
_NEGATION_WORDS = (" pas ", " plus ", " jamais ", " aucun")

def _norm_option(value: str) -> str:
    return normalize_text(value).replace("’", "'")

def _topic_axis_allowed(topic: str, axis: str) -> bool:
    key = normalize_text(topic)
    if "артикл" in key:
        return axis in {"article_contracted", "article_after_quantity", "article_after_negation"}
    if "cod" in key and "coi" not in key:
        return axis == "pronoun_cod"
    if "coi" in key:
        return axis == "pronoun_coi"
    if "en et y" in key:
        return axis == "pronoun_en_y"
    if "dont" in key:
        return axis == "relative_dont"
    if any(token in key for token in ("qui", "que", "où", "относитель", "auquel", "duquel", "lequel")):
        return axis == "relative_pronoun"
    if "двойн" in key:
        return axis == "double_pronouns"
    return axis == "general_grammar"

def validate_surface_contract(item: CandidateQuestion) -> list[str]:
    errors: list[str] = []
    prompt_has_blank = has_blank(item.prompt)

    if item.question_type == "translation":
        if prompt_has_blank:
            errors.append("translation_must_use_full_sentences")
        # Translation options must be complete French clauses, not isolated tokens.
        if any(len(option.split()) < 3 for option in item.options):
            errors.append("translation_options_must_be_complete_sentences")

    if item.question_type == "conjugation":
        if not prompt_has_blank:
            errors.append("conjugation_requires_one_blank")
        elif len(_BLANK_RE.findall(item.prompt)) != 1:
            errors.append("conjugation_requires_exactly_one_blank")
        # Options for a conjugation blank must be compact forms, not full clauses.
        if any(len(option.split()) > 3 for option in item.options):
            errors.append("conjugation_options_too_long")

    if item.question_type == "grammar_pronouns":
        if not prompt_has_blank or len(_BLANK_RE.findall(item.prompt)) != 1:
            errors.append("grammar_pronouns_requires_exactly_one_blank")
        if not _topic_axis_allowed(item.topic, item.comparison_axis):
            errors.append("grammar_topic_axis_mismatch")
        if any(len(option.split()) > 3 for option in item.options):
            errors.append("grammar_options_too_long")

        normalized_options = {_norm_option(option) for option in item.options}
        prompt_key = f" {normalize_text(item.prompt)} "
        correct = _norm_option(item.options[item.correct_option_id])

        if item.comparison_axis.startswith("article_"):
            if not normalized_options.issubset({_norm_option(x) for x in _ARTICLE_OPTIONS}):
                errors.append("article_options_outside_closed_set")
            if item.comparison_axis == "article_contracted":
                if not normalized_options.issubset(_CONTRACTED_ARTICLES):
                    errors.append("contracted_article_options_must_be_contracted")
                if correct not in _CONTRACTED_ARTICLES:
                    errors.append("contracted_article_correct_answer_invalid")
            elif item.comparison_axis == "article_after_quantity":
                if not any(marker in prompt_key for marker in _QUANTITY_MARKERS):
                    errors.append("article_quantity_context_missing")
                if correct not in {_norm_option(x) for x in _DE_FORMS}:
                    errors.append("article_quantity_correct_answer_must_be_de")
            elif item.comparison_axis == "article_after_negation":
                if not (any(marker in prompt_key for marker in _NEGATION_MARKERS) and
                        any(marker in prompt_key for marker in _NEGATION_WORDS)):
                    errors.append("article_negation_context_missing")
                if " être " in prompt_key or " est " in prompt_key or " sont " in prompt_key:
                    errors.append("article_negation_etre_exception_forbidden")
                if correct not in {_norm_option(x) for x in _DE_FORMS}:
                    errors.append("article_negation_correct_answer_must_be_de")

        if item.comparison_axis.startswith("pronoun_") or item.comparison_axis in {
            "relative_dont", "relative_pronoun", "double_pronouns"
        }:
            if not normalized_options.issubset({_norm_option(x) for x in _PRONOUN_OPTIONS}):
                errors.append("pronoun_options_outside_closed_set")

    if prompt_has_blank:
        for assembled in assemble_blank_variants(item.prompt, item.options):
            normalized = re.sub(r"\s+", " ", assembled).strip()
            if any(pattern.search(normalized) for pattern in _DOUBLE_CLITIC_PATTERNS):
                errors.append("blank_option_duplicates_pronoun_or_article")
                break

    return errors


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
    if len(item.explanation) < 20:
        errors.append("explanation_too_short")
    if not re.search(r"[А-Яа-яЁё]", item.explanation):
        errors.append("explanation_must_be_russian")
    explanation = item.explanation.strip()
    if not explanation.endswith((".", "!", "?")):
        errors.append("explanation_incomplete")
    if explanation.count("«") != explanation.count("»"):
        errors.append("explanation_unbalanced_quotes")
    if re.search(r"\b(и|но|или|потому что|так как)\s*[.!?]?$", explanation, re.I):
        errors.append("explanation_incomplete")

    if expected_type == "translation":
        if not re.search(r"[А-Яа-яЁё]", item.prompt):
            errors.append("translation_prompt_must_be_russian")
        if not all(re.search(r"[A-Za-zÀ-ÿ]", option) for option in item.options):
            errors.append("translation_options_must_be_french")

    # Conjugation clarity is defined by the structural contract, not by
    # cosmetic instruction words such as «Complétez» or «Выберите». A natural
    # Telegram quiz may consist only of a contextual French sentence with one
    # blank. validate_surface_contract() already requires exactly one blank and
    # compact options that can be inserted literally.

    errors.extend(validate_surface_contract(item))
    return errors
