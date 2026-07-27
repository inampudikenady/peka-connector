from datetime import UTC, datetime, timedelta, timezone
from typing import cast

import pytest
from sqlalchemy.engine.interfaces import Dialect

from app.infrastructure.database.types import UTCDateTime


def test_utc_datetime_restores_legacy_naive_values_as_utc() -> None:
    value = UTCDateTime().process_result_value(
        datetime(2026, 7, 21, 6, 11), cast(Dialect, object())
    )
    assert value == datetime(2026, 7, 21, 6, 11, tzinfo=UTC)


def test_utc_datetime_normalizes_aware_values_and_rejects_naive_writes() -> None:
    column = UTCDateTime()
    source = datetime(2026, 7, 21, 11, 41, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert column.process_bind_param(source, cast(Dialect, object())) == datetime(
        2026, 7, 21, 6, 11, tzinfo=UTC
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        column.process_bind_param(datetime(2026, 7, 21, 6, 11), cast(Dialect, object()))
