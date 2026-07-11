import json
from types import SimpleNamespace

import pytest

import openai_service
from schemas import CandidateQuestion


def valid_candidate_json() -> str:
    return json.dumps(
        {
            "topic": "Живая фраза",
            "skill": "Перевод",
            "level": "A1-A2",
            "question_type": "translation",
            "prompt": "Как сказать: «Я уже поел»?",
            "options": [
                "J’ai déjà mangé.",
                "Je mange déjà.",
                "Je vais déjà manger.",
                "J’avais déjà mange.",
            ],
            "correct_option_id": 0,
            "explanation": "Passé composé обозначает завершённое действие.",
        },
        ensure_ascii=False,
    )


def fake_completion(content: str, finish_reason: str = "stop"):
    message = SimpleNamespace(content=content, refusal=None)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


def test_chat_completion_json_validates(monkeypatch):
    monkeypatch.setattr(
        openai_service.client.chat.completions,
        "create",
        lambda **_: fake_completion(valid_candidate_json()),
    )
    result = openai_service._request_json(
        model="gpt-5-mini",
        instructions="x",
        user_input="y",
        schema=CandidateQuestion,
        schema_name="candidate",
        max_completion_tokens=500,
        reasoning_effort="low",
    )
    assert result.correct_option_id == 0
    assert result.level == "A1-A2"


def test_empty_content_has_clear_error(monkeypatch):
    monkeypatch.setattr(
        openai_service.client.chat.completions,
        "create",
        lambda **_: fake_completion(""),
    )
    with pytest.raises(RuntimeError, match="empty structured response"):
        openai_service._request_json(
            model="gpt-5-mini",
            instructions="x",
            user_input="y",
            schema=CandidateQuestion,
            schema_name="candidate",
            max_completion_tokens=500,
            reasoning_effort="low",
        )


def test_invalid_json_has_clear_error(monkeypatch):
    monkeypatch.setattr(
        openai_service.client.chat.completions,
        "create",
        lambda **_: fake_completion("not json"),
    )
    with pytest.raises(RuntimeError, match="invalid JSON"):
        openai_service._request_json(
            model="gpt-5-mini",
            instructions="x",
            user_input="y",
            schema=CandidateQuestion,
            schema_name="candidate",
            max_completion_tokens=500,
            reasoning_effort="low",
        )


def test_length_finish_reason_retries_with_larger_budget(monkeypatch):
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return fake_completion("", finish_reason="length")
        return fake_completion(valid_candidate_json())

    monkeypatch.setattr(
        openai_service.client.chat.completions,
        "create",
        create,
    )
    result = openai_service._request_json(
        model="gpt-5-mini",
        instructions="x",
        user_input="y",
        schema=CandidateQuestion,
        schema_name="candidate",
        max_completion_tokens=500,
        reasoning_effort="low",
    )
    assert result.correct_option_id == 0
    assert len(calls) == 2
    assert calls[0]["reasoning_effort"] == "low"
    assert calls[1]["reasoning_effort"] == "minimal"
    assert calls[1]["max_completion_tokens"] > calls[0]["max_completion_tokens"]


def test_repeated_length_finish_reason_has_clear_error(monkeypatch):
    monkeypatch.setattr(
        openai_service.client.chat.completions,
        "create",
        lambda **_: fake_completion("", finish_reason="length"),
    )
    with pytest.raises(RuntimeError, match="truncated"):
        openai_service._request_json(
            model="gpt-5-mini",
            instructions="x",
            user_input="y",
            schema=CandidateQuestion,
            schema_name="candidate",
            max_completion_tokens=500,
            reasoning_effort="low",
        )
