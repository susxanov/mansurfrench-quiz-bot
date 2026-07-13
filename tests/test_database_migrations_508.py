from pathlib import Path

from sqlalchemy import Text

import db
from models import DailyBlock, Question


def test_generated_metadata_uses_unbounded_text_columns():
    assert isinstance(Question.__table__.c.topic.type, Text)
    assert isinstance(Question.__table__.c.skill.type, Text)
    assert isinstance(DailyBlock.__table__.c.session.type, Text)
    assert isinstance(DailyBlock.__table__.c.topic.type, Text)


def test_postgres_migrations_widen_legacy_varchar_columns():
    statements = "\n".join(db._POSTGRES_SAFE_MIGRATIONS).lower()
    assert "questions alter column skill type text" in statements
    assert "questions alter column topic type text" in statements
    assert "daily_blocks alter column session type text" in statements


def test_service_flushes_question_inserts_explicitly():
    source = Path("service.py").read_text(encoding="utf-8")
    marker = "db.flush()\n            block = db.get(DailyBlock, block_id)"
    assert marker in source
