from datetime import date
from unittest.mock import patch

import pytest

import service


SUNDAY = date(2026, 7, 12)


def test_sunday_rejected_without_force():
    with pytest.raises(RuntimeError, match="воскресенье"):
        service.prepare_block(SUNDAY, "morning", force=False)


def test_sunday_force_reaches_database_logic():
    with patch.object(
        service,
        "session_scope",
        side_effect=RuntimeError("database reached"),
    ):
        with pytest.raises(RuntimeError, match="database reached"):
            service.prepare_block(SUNDAY, "morning", force=True)


def test_manual_force_uses_unique_session_key():
    from unittest.mock import patch
    import admin

    captured = {}

    def fake_send_for_approval(target_date, session, force=False):
        captured['session'] = session
        captured['force'] = force
        return 'ok'

    with patch.object(admin, 'send_for_approval', side_effect=fake_send_for_approval), \
         patch.object(admin, 'send_text'):
        admin._manual_prepare('morning', force=True)

    assert captured['force'] is True
    assert captured['session'].startswith('test_m_')
    assert len(captured['session']) <= 20
    assert captured['session'] != 'morning'
