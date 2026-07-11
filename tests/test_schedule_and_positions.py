from datetime import date

from service import _move_correct_answer, _target_positions, is_workday
from schemas import CandidateQuestion
from topics import LEXICAL_TOPICS, third_question_plan


def make_question():
    return CandidateQuestion(
        topic="Présent",
        skill="aller",
        level="A1-A2",
        question_type="conjugation",
        prompt="Choisissez la bonne forme.",
        options=["vais", "vas", "va", "allons"],
        correct_option_id=0,
        explanation="С местоимением je глагол aller имеет форму je vais.",
    )


def test_weekdays_only():
    assert is_workday(date(2026, 7, 13))
    assert not is_workday(date(2026, 7, 11))
    assert not is_workday(date(2026, 7, 12))


def test_positions_are_mixed():
    morning = _target_positions(date(2026, 7, 13), "morning")
    evening = _target_positions(date(2026, 7, 13), "evening")
    assert len(set(morning)) == 3
    assert len(set(evening)) == 3
    assert morning != evening
    assert all(0 <= value <= 3 for value in morning + evening)


def test_move_correct_answer_keeps_correct_text():
    question = make_question()
    _move_correct_answer(question, 3)
    assert question.correct_option_id == 3
    assert question.options[3] == "vais"


def test_twelve_lexical_topics_exist():
    assert len(LEXICAL_TOPICS) == 12


def test_morning_and_evening_rotation_differs():
    target = date(2026, 7, 13)
    assert third_question_plan(target, "morning") != third_question_plan(
        target,
        "evening",
    )
