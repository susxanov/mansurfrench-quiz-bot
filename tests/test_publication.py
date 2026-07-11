from datetime import date

import pytest
from sqlalchemy import delete

import service
from db import init_db, session_scope
from models import DailyBlock, Question
from schemas import CandidateQuestion


def reset_db():
    init_db()
    with session_scope() as db:
        db.execute(delete(Question))
        db.execute(delete(DailyBlock))


def seed_block():
    with session_scope() as db:
        block = DailyBlock(
            target_date=date(2026, 7, 13),
            session="morning",
            level="A1-A2",
            topic="3 вопроса",
            status="pending_approval",
            approved=False,
        )
        db.add(block)
        db.flush()

        for position in range(1, 4):
            db.add(
                Question(
                    block_id=block.id,
                    position=position,
                    fingerprint=f"fp-{position}",
                    topic="Test",
                    skill="Test",
                    question_type="translation",
                    prompt=f"Переведите фразу {position}.",
                    options=["A", "B", "C", "D"],
                    correct_option_ids=[position % 4],
                    explanation="Правильный вариант соответствует контексту фразы.",
                    comparison_axis="",
                    surface_constraints={},
                    reviewer_score=100,
                    reviewer_notes="ok",
                )
            )
        return block.id


def test_publication_is_idempotent(monkeypatch):
    reset_db()
    block_id = seed_block()
    calls = []

    def fake_send(question, chat_id=None):
        calls.append(question.id)
        return {"message_id": 1000 + len(calls)}

    monkeypatch.setattr(service, "send_quiz", fake_send)
    monkeypatch.setattr(service.time, "sleep", lambda *_: None)

    assert "опубликовано 3" in service.publish_block_by_id(block_id)
    assert len(calls) == 3

    assert "уже опубликован" in service.publish_block_by_id(block_id)
    assert len(calls) == 3


def test_partial_failure_resumes_without_duplicates(monkeypatch):
    reset_db()
    block_id = seed_block()
    calls = []
    fail_once = {"done": False}

    def flaky_send(question, chat_id=None):
        calls.append(question.id)
        if len(calls) == 2 and not fail_once["done"]:
            fail_once["done"] = True
            raise RuntimeError("temporary Telegram failure")
        return {"message_id": 2000 + len(calls)}

    monkeypatch.setattr(service, "send_quiz", flaky_send)
    monkeypatch.setattr(service.time, "sleep", lambda *_: None)

    with pytest.raises(RuntimeError, match="temporary Telegram failure"):
        service.publish_block_by_id(block_id)

    # First question was persisted. Retry sends only questions 2 and 3.
    assert "опубликовано 3" in service.publish_block_by_id(block_id)
    assert calls.count(calls[0]) == 1
    assert len(calls) == 4
