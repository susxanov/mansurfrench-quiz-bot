from datetime import date
from unittest.mock import patch

import pytest

import service


SATURDAY = date(2026, 7, 11)


def test_weekend_rejected_without_force():
    with pytest.raises(RuntimeError, match="субботу"):
        service.prepare_block(SATURDAY, "morning", force=False)


def test_weekend_force_reaches_database_logic():
    with patch.object(
        service,
        "session_scope",
        side_effect=RuntimeError("database reached"),
    ):
        with pytest.raises(RuntimeError, match="database reached"):
            service.prepare_block(SATURDAY, "morning", force=True)
