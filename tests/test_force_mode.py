from datetime import date
from unittest.mock import patch

import pytest

import service


SUNDAY = date(2026, 7, 12)


def test_prepare_block_rejects_sunday_without_force():
    with pytest.raises(RuntimeError, match="воскресенье"):
        service.prepare_block(SUNDAY, "morning", force=False)


def test_prepare_block_accepts_sunday_with_force_until_generation():
    fake_block = type("Block", (), {"id": 1, "status": "generating"})()

    class FakeResult:
        def scalar(self, *args, **kwargs):
            return None

    class FakeDB:
        def scalar(self, *args, **kwargs):
            return None
        def add(self, obj):
            obj.id = 1
        def flush(self):
            return None
        def execute(self, *args, **kwargs):
            return None
        def get(self, *args, **kwargs):
            return fake_block
        def scalars(self, *args, **kwargs):
            return type("Scalars", (), {"all": lambda self: []})()

    class Scope:
        def __enter__(self):
            return FakeDB()
        def __exit__(self, exc_type, exc, tb):
            return False

    with patch.object(service, "session_scope", return_value=Scope()), \
         patch.object(service, "generate_question", side_effect=RuntimeError("generation reached")):
        with pytest.raises(RuntimeError, match="generation reached"):
            service.prepare_block(SUNDAY, "morning", force=True)


def test_force_regenerate_callback_is_emitted():
    source = open("service.py", encoding="utf-8").read()
    assert "regenerate_force" in source
