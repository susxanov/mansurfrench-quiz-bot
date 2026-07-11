from schemas import CandidateQuestion
from quality import (
    fingerprint,
    is_duplicate_or_similar,
    prompts_too_similar,
    validate_question,
)
from text_utils import clean_quiz_prompt


def make_question(prompt="Choisissez la bonne forme."):
    return CandidateQuestion(
        topic="Présent",
        skill="aller au présent",
        level="A1-A2",
        question_type="conjugation",
        prompt=prompt,
        options=["vais", "vas", "va", "allons"],
        correct_option_id=0,
        explanation="С местоимением je глагол aller имеет форму je vais.",
    )


def test_removes_internal_prefixes():
    assert (
        clean_quiz_prompt(
            "Exercice 193-e-t-1. Переведите: «Я иду домой»."
        )
        == "Переведите: «Я иду домой»."
    )
    assert (
        clean_quiz_prompt("Question 12 — Choisissez la bonne forme.")
        == "Choisissez la bonne forme."
    )


def test_validation_rejects_internal_prefix():
    item = make_question("Exercice 12. Choisissez la bonne forme.")
    errors = validate_question(
        item,
        "A1-A2",
        "conjugation",
        raw_prompt="Exercice 12. Choisissez la bonne forme.",
    )
    assert "internal_prefix" in errors


def test_fingerprint_ignores_option_order():
    first = make_question()
    second = make_question()
    second.options = list(reversed(second.options))
    second.correct_option_id = 3
    assert fingerprint(first) == fingerprint(second)


def test_similarity_detection():
    assert prompts_too_similar(
        "Переведите: «Я записался к стоматологу на завтра».",
        "Переведите: «Я записался к стоматологу на завтра утром».",
        threshold=0.70,
    )
    assert is_duplicate_or_similar(
        "Переведите: «Я записался к стоматологу на завтра».",
        ["Переведите: «Я записался к стоматологу на завтра утром»."],
    )
