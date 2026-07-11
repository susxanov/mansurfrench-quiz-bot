from datetime import date

import service
from schemas import CandidateQuestion


def candidate(question_type, index):
    return CandidateQuestion(
        topic=f"Topic {index}",
        skill=f"Skill {index}",
        level="A1-A2",
        question_type=question_type,
        prompt=f"Уникальный вопрос номер {index}?",
        options=[
            f"Option {index} A",
            f"Option {index} B",
            f"Option {index} C",
            f"Option {index} D",
        ],
        correct_option_id=0,
        explanation="Правильный ответ соответствует проверяемой форме и контексту.",
    )


def test_question_plan_has_required_three_types(monkeypatch):
    monkeypatch.setattr(
        service,
        "third_question_plan",
        lambda *_: ("lexicon", "Больница"),
    )
    assert [item[0] for item in service._question_plan(
        date(2026, 7, 13),
        "morning",
    )] == ["translation", "conjugation", "lexicon"]
