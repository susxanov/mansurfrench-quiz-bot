from types import SimpleNamespace

import pytest

import openai_service
from schemas import CandidateQuestion


def valid_candidate_json():
    return '''{
      "topic": "Бытовая речь",
      "skill": "Перевод",
      "level": "A1-A2",
      "question_type": "translation",
      "prompt": "Как сказать: «Я только что пришёл»?",
      "options": ["Je viens d'arriver.", "Je vais arriver.", "J'arrivais.", "Je suis arrivé demain."],
      "correct_option_id": 0,
      "explanation": "Passé récent образуется с venir de и инфинитивом."
    }'''


def test_extracts_output_text_and_validates(monkeypatch):
    fake = SimpleNamespace(output_text=valid_candidate_json())
    monkeypatch.setattr(
        openai_service.client.responses,
        "create",
        lambda **_: fake,
    )
    result = openai_service._request_json(
        model="gpt-5-mini",
        instructions="x",
        user_input="y",
        schema=CandidateQuestion,
        max_output_tokens=500,
    )
    assert result.correct_option_id == 0
    assert result.level == "A1-A2"


def test_accepts_markdown_fenced_json(monkeypatch):
    fake = SimpleNamespace(output_text="```json\n" + valid_candidate_json() + "\n```")
    monkeypatch.setattr(openai_service.client.responses, "create", lambda **_: fake)
    result = openai_service._request_json(
        model="gpt-5-mini",
        instructions="x",
        user_input="y",
        schema=CandidateQuestion,
        max_output_tokens=500,
    )
    assert len(result.options) == 4


def test_invalid_json_has_clear_error(monkeypatch):
    fake = SimpleNamespace(output_text="not json")
    monkeypatch.setattr(openai_service.client.responses, "create", lambda **_: fake)
    with pytest.raises(RuntimeError, match="invalid JSON"):
        openai_service._request_json(
            model="gpt-5-mini",
            instructions="x",
            user_input="y",
            schema=CandidateQuestion,
            max_output_tokens=500,
        )
