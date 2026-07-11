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
