from datetime import datetime

from app.booking import STOCKHOLM_TZ, parse_requested_datetime


def _assert_stockholm_datetime(parsed_iso: str, expected_date: str, expected_time: str) -> None:
    parsed_dt = datetime.fromisoformat(parsed_iso)
    assert parsed_dt.tzinfo is not None
    local = parsed_dt.astimezone(STOCKHOLM_TZ)
    assert local.strftime("%Y-%m-%d") == expected_date
    assert local.strftime("%H:%M") == expected_time


def test_parse_requested_datetime_time_on_date() -> None:
    parsed = parse_requested_datetime("14:00 on 2026-02-17")
    assert parsed is not None
    _assert_stockholm_datetime(parsed, "2026-02-17", "14:00")


def test_parse_requested_datetime_on_date_at_time() -> None:
    parsed = parse_requested_datetime("on 2026-02-17 at 14:00")
    assert parsed is not None
    _assert_stockholm_datetime(parsed, "2026-02-17", "14:00")


def test_parse_requested_datetime_date_at_time() -> None:
    parsed = parse_requested_datetime("2026-02-17 at 14:00")
    assert parsed is not None
    _assert_stockholm_datetime(parsed, "2026-02-17", "14:00")


def test_parse_requested_datetime_date_time_still_supported() -> None:
    parsed = parse_requested_datetime("2026-02-17 14:00")
    assert parsed is not None
    _assert_stockholm_datetime(parsed, "2026-02-17", "14:00")
