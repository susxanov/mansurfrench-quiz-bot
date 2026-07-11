from datetime import date
from pathlib import Path
from unittest.mock import patch

import admin
import service
from topics import working_day_index


def test_force_session_fits_database_column_and_maps_to_morning():
    captured = {}

    def fake_send_for_approval(target_date, session, force=False):
        captured["session"] = session
        captured["force"] = force
        return "ok"

    with patch.object(admin, "send_for_approval", side_effect=fake_send_for_approval), \
         patch.object(admin, "send_text"):
        admin._manual_prepare("morning", force=True)

    key = captured["session"]
    assert captured["force"] is True
    assert key.startswith("test_m_")
    assert len(key) <= 20
    assert service.base_session(key) == "morning"


def test_force_session_maps_to_evening():
    assert service.base_session("test_e_174012123456") == "evening"


def test_startup_catchup_skips_only_sunday():
    source = Path("main.py").read_text(encoding="utf-8")
    assert "if now.weekday() >= 6:" in source
    assert "if now.weekday() >= 5:" not in source


def test_topic_rotation_counts_saturday_as_workday():
    friday = working_day_index(date(2026, 7, 10))
    saturday = working_day_index(date(2026, 7, 11))
    sunday = working_day_index(date(2026, 7, 12))
    assert saturday == friday + 1
    assert sunday == saturday
