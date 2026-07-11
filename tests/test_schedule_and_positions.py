from service import _move_correct_answer, _target_positions, is_workday
from schemas import CandidateQuestion
from topics import LEXICAL_TOPICS


class WeekdayStub:
    """Calendar-independent object exposing Python's weekday() contract."""

    def __init__(self, weekday_number: int):
        self.weekday_number = weekday_number

    def weekday(self) -> int:
        return self.weekday_number


class OrdinalStub(WeekdayStub):
    def __init__(self, weekday_number: int, ordinal: int):
        super().__init__(weekday_number)
        self._ordinal = ordinal

    def toordinal(self) -> int:
        return self._ordinal


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


def test_monday_through_saturday_are_workdays():
    # Python weekday(): Monday=0, ..., Saturday=5, Sunday=6.
    for weekday_number in range(6):
        assert is_workday(WeekdayStub(weekday_number))


def test_sunday_is_the_only_day_off():
    assert not is_workday(WeekdayStub(6))


def test_positions_are_mixed_between_sessions():
    target = OrdinalStub(0, 739815)
    morning = _target_positions(target, "morning")
    evening = _target_positions(target, "evening")
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
