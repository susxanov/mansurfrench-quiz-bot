from quality import validate_question
from schemas import CandidateQuestion


def conjugation(prompt: str) -> CandidateQuestion:
    return CandidateQuestion(
        topic="Conditionnel présent",
        skill="Conjugaison en contexte",
        level="B1-B2",
        question_type="conjugation",
        prompt=prompt,
        options=["appellerais", "appellerai", "appelais", "ai appelé"],
        correct_option_id=0,
        explanation=(
            "После si + imparfait главное предложение ставится в conditionnel présent."
        ),
    )


def test_contextual_conjugation_prompt_does_not_need_instruction_word():
    item = conjugation("Si j’avais ton numéro, je t’___.")
    errors = validate_question(item, "B1-B2", "conjugation")
    assert "conjugation_prompt_unclear" not in errors
    assert errors == []


def test_conjugation_without_blank_is_rejected_by_structure():
    item = conjugation("Si j’avais ton numéro, je t’appellerais.")
    errors = validate_question(item, "B1-B2", "conjugation")
    assert "conjugation_requires_one_blank" in errors


def test_conjugation_with_two_blanks_is_rejected_by_structure():
    item = conjugation("Si j’___ ton numéro, je t’___")
    errors = validate_question(item, "B1-B2", "conjugation")
    assert "conjugation_requires_exactly_one_blank" in errors
