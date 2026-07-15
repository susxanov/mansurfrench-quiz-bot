from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CandidateQuestion(StrictModel):
    topic: str = Field(min_length=2, max_length=120)
    skill: str = Field(min_length=2, max_length=100)
    level: Literal["A1-A2", "B1-B2"]
    question_type: Literal["translation", "conjugation", "lexicon", "grammar_pronouns"]
    comparison_axis: Literal[
        "translation_full_sentence",
        "conjugation_verb_form",
        "lexicon_context",
        "pronoun_cod",
        "pronoun_coi",
        "pronoun_en_y",
        "relative_dont",
        "relative_pronoun",
        "double_pronouns",
        "article_contracted",
        "article_after_quantity",
        "article_after_negation",
        "general_grammar",
    ] = "general_grammar"
    prompt: str = Field(min_length=5, max_length=300)
    options: list[str] = Field(min_length=4, max_length=4)
    correct_option_id: int = Field(ge=0, le=3)
    explanation: str = Field(min_length=20, max_length=190)

    @field_validator("topic", "skill", "prompt", "explanation")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()

    @field_validator("options")
    @classmethod
    def validate_options(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value]
        if len(cleaned) != 4 or len(set(cleaned)) != 4:
            raise ValueError("Exactly four distinct options are required")
        if any(not option or len(option) > 100 for option in cleaned):
            raise ValueError("Invalid option length")
        return cleaned


class ReviewResult(StrictModel):
    approved: bool
    verified_correct_option_id: int = Field(ge=0, le=3)
    issues: list[str] = Field(min_length=0, max_length=10)
    explanation_check: str = Field(min_length=5, max_length=300)
