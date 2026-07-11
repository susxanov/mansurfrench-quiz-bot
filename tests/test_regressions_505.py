
from pathlib import Path

from quality import validate_question
from schemas import CandidateQuestion


def make_question(explanation: str) -> CandidateQuestion:
    return CandidateQuestion(
        topic="Условные конструкции",
        skill="si + imparfait + conditionnel présent",
        level="B1-B2",
        question_type="translation",
        prompt="Как сказать: «Если бы у меня было время, я бы тебе помог»?",
        options=[
            "Si j'avais le temps, je t'aiderais.",
            "Si j'aurai le temps, je t'aiderais.",
            "Si j'aurais le temps, je t'aiderais.",
            "Si j'avais le temps, je t'aiderai.",
        ],
        correct_option_id=0,
        explanation=explanation,
    )


def test_incomplete_explanation_is_rejected():
    item = make_question("После si используется imparfait, а в главной части и")
    errors = validate_question(item, "B1-B2", "translation")
    assert "explanation_incomplete" in errors


def test_complete_explanation_is_accepted():
    item = make_question(
        "Для нереального условия: si + imparfait, затем conditionnel présent."
    )
    errors = validate_question(item, "B1-B2", "translation")
    assert "explanation_incomplete" not in errors


def test_generator_receives_reviewer_feedback_on_retry():
    source = Path("openai_service.py").read_text(encoding="utf-8")
    assert "correction_feedback = str(exc)" in source
    assert "Исправь конкретные ошибки предыдущей попытки" in source


def test_morning_and_evening_have_separate_prepare_locks():
    source = Path("service.py").read_text(encoding="utf-8")
    assert '_prepare_locks = {"morning": threading.Lock(), "evening": threading.Lock()}' in source
    assert "prepare_lock = _prepare_locks[effective_session]" in source


def test_test_command_is_supported_as_force_alias():
    source = Path("admin.py").read_text(encoding="utf-8")
    assert 'cmd in {"/force", "/test"}' in source
