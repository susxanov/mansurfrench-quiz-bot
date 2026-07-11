from pathlib import Path


def test_scheduler_uses_monday_through_saturday_for_both_jobs():
    source = Path("main.py").read_text(encoding="utf-8")
    assert source.count('day_of_week="mon-sat"') == 2
    assert 'day_of_week="mon-fri"' not in source


def test_runtime_guard_skips_only_sunday():
    source = Path("main.py").read_text(encoding="utf-8")
    assert "if today.weekday() >= 6:" in source


def test_service_rule_matches_scheduler_rule():
    source = Path("service.py").read_text(encoding="utf-8")
    assert "return target_date.weekday() < 6" in source
    assert "В воскресенье бот не работает." in source


def test_startup_catchup_also_allows_saturday():
    source = Path("main.py").read_text(encoding="utf-8")
    assert "if now.weekday() >= 6:" in source
    assert "if now.weekday() >= 5:" not in source


def test_topic_rotation_counts_saturday_as_workday():
    source = Path("topics.py").read_text(encoding="utf-8")
    assert "if current.weekday() < 6:" in source
    assert "if current.weekday() < 5:" not in source
