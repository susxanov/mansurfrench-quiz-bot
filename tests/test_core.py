from datetime import date
from schemas import CandidateQuestion
from service import _move_correct_answer, _target_positions, is_workday
from text_utils import clean_quiz_prompt
from quality import fingerprint
from topics import third_question_plan


def make_question():
    return CandidateQuestion(
        topic="Présent",
        skill="aller au présent",
        level="A1-A2",
        question_type="conjugation",
        prompt="Choisissez la bonne forme.",
        options=["vais", "vas", "va", "allons"],
        correct_option_id=0,
        explanation="Avec je, le verbe aller se conjugue « je vais » au présent.",
    )


def test_weekdays_only():
    assert is_workday(date(2026, 7, 13))
    assert not is_workday(date(2026, 7, 12))


def test_prompt_cleanup():
    assert clean_quiz_prompt("Exercice 193-e-t-1. Переведите: «Я иду домой».") == "Переведите: «Я иду домой»."


def test_answer_positions_are_distinct():
    positions = _target_positions(date(2026, 7, 13), "morning")
    assert len(positions) == 3
    assert len(set(positions)) == 3
    assert all(0 <= p <= 3 for p in positions)


def test_move_correct_answer():
    q = make_question()
    _move_correct_answer(q, 3)
    assert q.correct_option_id == 3
    assert q.options[3] == "vais"


def test_fingerprint_ignores_option_order():
    q1 = make_question()
    q2 = make_question()
    q2.options = list(reversed(q2.options))
    q2.correct_option_id = 3
    assert fingerprint(q1) == fingerprint(q2)


def test_third_question_rotates():
    a = third_question_plan(date(2026, 7, 13), "morning")
    b = third_question_plan(date(2026, 7, 14), "morning")
    assert a[0] != b[0]
