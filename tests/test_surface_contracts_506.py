from schemas import CandidateQuestion
from quality import validate_question, assemble_blank_variants


def make_item(**overrides):
    data = {
        "topic": "conditionnel",
        "skill": "hypothèse",
        "level": "B1-B2",
        "question_type": "conjugation",
        "prompt": "Complétez : Si j’avais ton numéro, je t’___.",
        "options": ["appellerais", "appellerai", "appelais", "ai appelé"],
        "correct_option_id": 0,
        "explanation": "Après si + imparfait, on emploie le conditionnel présent dans la principale.",
    }
    data.update(overrides)
    return CandidateQuestion(**data)


def test_rejects_double_pronoun_after_blank_substitution():
    item = make_item(
        prompt="Complétez : Si j’avais ton numéro, je te ___.",
        options=["t’appellerais", "t’appellerai", "t’appelais", "t’ai appelé"],
    )
    errors = validate_question(item, "B1-B2", "conjugation")
    assert "blank_option_duplicates_pronoun_or_article" in errors


def test_accepts_pronoun_owned_by_prompt():
    item = make_item()
    errors = validate_question(item, "B1-B2", "conjugation")
    assert "blank_option_duplicates_pronoun_or_article" not in errors
    assert "conjugation_requires_one_blank" not in errors


def test_translation_must_not_contain_blank():
    item = make_item(
        question_type="translation",
        prompt="Как перевести: Si j’avais ton numéro, je ___ ?",
        options=[
            "Si j’avais ton numéro, je t’appellerais.",
            "Si j’aurais ton numéro, je t’appellerais.",
            "Si j’avais ton numéro, je t’appellerai.",
            "Si j’avais eu ton numéro, je t’appellerais.",
        ],
    )
    errors = validate_question(item, "B1-B2", "translation")
    assert "translation_must_use_full_sentences" in errors


def test_translation_full_sentences_contract():
    item = make_item(
        question_type="translation",
        prompt="Как сказать по-французски: «Если бы у меня был твой номер, я бы тебе позвонил»?",
        options=[
            "Si j’avais ton numéro, je t’appellerais.",
            "Si j’aurais ton numéro, je t’appellerais.",
            "Si j’avais ton numéro, je t’appellerai.",
            "Si j’avais eu ton numéro, je t’appellerais.",
        ],
    )
    errors = validate_question(item, "B1-B2", "translation")
    assert "translation_must_use_full_sentences" not in errors
    assert "translation_options_must_be_complete_sentences" not in errors


def test_assemble_blank_variants_is_literal():
    assembled = assemble_blank_variants("Je t’___ demain.", ["appellerai"])
    assert assembled == ["Je t’appellerai demain."]
