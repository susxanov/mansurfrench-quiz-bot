from schemas import CandidateQuestion
from quality import validate_question


def test_rejects_wrong_level_and_visible_label():
    q = CandidateQuestion(
        topic="Test",
        skill="Test",
        level="B1-B2",
        question_type="translation",
        prompt="Exercice 12. Переведите: «Я дома».",
        options=["Je suis chez moi.", "Je vais chez moi.", "J’étais chez moi.", "Je reste maison."],
        correct_option_id=0,
        explanation="Je suis chez moi signifie «я дома» dans la langue courante.",
    )
    errors = validate_question(q, "A1-A2", "translation")
    assert "wrong_level" in errors
    assert "internal_or_forbidden_text" in errors


def test_accepts_clean_translation():
    q = CandidateQuestion(
        topic="Vie quotidienne",
        skill="être chez soi",
        level="A1-A2",
        question_type="translation",
        prompt="Переведите: «Я сейчас дома».",
        options=["Je suis chez moi maintenant.", "Je vais chez moi maintenant.", "J’étais chez moi maintenant.", "Je reste à maison maintenant."],
        correct_option_id=0,
        explanation="Je suis chez moi означает «я дома»; maintenant уточняет, что речь идёт о текущем моменте.",
    )
    assert validate_question(q, "A1-A2", "translation") == []
