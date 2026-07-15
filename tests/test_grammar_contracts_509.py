from schemas import CandidateQuestion
from quality import validate_question
from topics import fallback_topics


def item(**overrides):
    data = {
        "topic": "Артикли: défini, indéfini, partitif, contracté",
        "skill": "article contracté après à",
        "level": "A1-A2",
        "question_type": "grammar_pronouns",
        "comparison_axis": "article_contracted",
        "prompt": "Demain, nous allons ___ cinéma.",
        "options": ["au", "aux", "du", "des"],
        "correct_option_id": 0,
        "explanation": "Перед существительным мужского рода à + le сливаются в форму «au».",
    }
    data.update(overrides)
    return CandidateQuestion(**data)


def test_rejects_ambiguous_generic_article_choice_from_real_incident():
    q = item(
        comparison_axis="general_grammar",
        prompt="Je voudrais acheter ___ pommes au marché.",
        options=["des", "les", "de", "aux"],
        correct_option_id=0,
    )
    errors = validate_question(q, "A1-A2", "grammar_pronouns")
    assert "grammar_topic_axis_mismatch" in errors


def test_rejects_fake_quantity_axis_without_quantity_trigger():
    q = item(
        comparison_axis="article_after_quantity",
        prompt="Je voudrais acheter ___ pommes au marché.",
        options=["de", "des", "les", "aux"],
        correct_option_id=0,
    )
    errors = validate_question(q, "A1-A2", "grammar_pronouns")
    assert "article_quantity_context_missing" in errors


def test_accepts_deterministic_article_after_quantity():
    q = item(
        comparison_axis="article_after_quantity",
        prompt="Je voudrais acheter beaucoup ___ pommes.",
        options=["de", "des", "les", "aux"],
        correct_option_id=0,
    )
    errors = validate_question(q, "A1-A2", "grammar_pronouns")
    assert "article_quantity_context_missing" not in errors
    assert "article_quantity_correct_answer_must_be_de" not in errors
    assert "grammar_topic_axis_mismatch" not in errors


def test_accepts_deterministic_contracted_article():
    errors = validate_question(item(), "A1-A2", "grammar_pronouns")
    assert not [e for e in errors if e.startswith("article_") or e.startswith("grammar_") or e.startswith("contracted_")]


def test_grammar_fallbacks_leave_ambiguous_article_topic():
    topics = fallback_topics(
        "grammar_pronouns",
        "Артикли: défini, indéfini, partitif, contracté",
    )
    assert topics[0].startswith("Артикли")
    assert "Pronoms EN et Y" in topics
    assert "DONT" in topics
    assert len(topics) == len(set(topics))
