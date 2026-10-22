"""Forecast aggregation regression tests independent of Home Assistant."""

import importlib.util
import math
from datetime import UTC, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from conftest import ROOT


def _module():
    spec = importlib.util.spec_from_file_location(
        "fmi_forecast_aggregation", ROOT / "forecast.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HELSINKI = ZoneInfo("Europe/Helsinki")
NOW = datetime(2026, 10, 22, 10, tzinfo=UTC)


def _point(time_str, *, temperature=3.0, precipitation=0.1, symbol=2, **values):
    defaults = {
        "wind_speed": 4.0,
        "wind_direction": 180.0,
        "pressure": 1012.0,
        "humidity": 80.0,
        "cloud_cover": 40.0,
        "dew_point": 1.0,
        "wind_gust": 6.0,
    }
    defaults.update(values)
    defaults.update(temperature=temperature, precipitation_amount=precipitation)
    return SimpleNamespace(
        time=datetime.fromisoformat(time_str),
        symbol=SimpleNamespace(value=symbol) if symbol is not None else None,
        **{key: SimpleNamespace(value=value) if value is not None else None
           for key, value in defaults.items()},
    )


def _build(points, *, daily=False, hourly_precipitation=True, now=NOW):
    return _module().build_forecast(
        points,
        daily=daily,
        to_local=lambda value: value.astimezone(HELSINKI),
        get_condition=lambda symbol: f"symbol-{symbol}",
        hourly_precipitation=hourly_precipitation,
        now=now,
    )


def test_hourly_preserves_native_fields_and_sorted_utc_order():
    points = [
        _point("2026-12-30T12:00:00+00:00", temperature=8),
        _point("2026-12-30T10:00:00+00:00", temperature=4),
        _point("2026-12-30T11:00:00+00:00", temperature=5),
    ]
    forecasts = _build(points)
    assert [item["native_temperature"] for item in forecasts] == [4, 5, 8]
    assert forecasts[0]["datetime"] == "2026-12-30T12:00:00+02:00"
    assert forecasts[0]["native_pressure"] == 1012
    assert forecasts[0]["native_wind_gust_speed"] == 6
    assert forecasts[0]["native_dew_point"] == 1
    assert "native_templow" not in forecasts[0]


def test_daily_groups_by_complete_local_date_across_new_year():
    points = [
        _point("2026-12-31T21:00:00+00:00", temperature=10),
        _point("2026-12-31T23:00:00+00:00", temperature=2),
        _point("2027-01-01T08:00:00+00:00", temperature=5),
    ]
    daily = _build(points, daily=True)
    assert [p["datetime"] for p in daily] == [
        "2026-12-31T00:00:00+02:00",
        "2027-01-01T00:00:00+02:00",
    ]
    assert daily[0]["native_temperature"] == 10
    assert daily[1]["native_temperature"] == 5
    assert daily[1]["native_templow"] == 2


def test_dst_fall_back_repeated_clock_hour_not_deduplicated():
    points = [
        _point("2026-10-25T01:15:00+00:00", temperature=2),
        _point("2026-10-25T00:15:00+00:00", temperature=1),
    ]
    hourly = _build(points, now=NOW)
    assert len(hourly) == 2
    assert hourly[0]["datetime"] == "2026-10-25T03:15:00+03:00"
    assert hourly[1]["datetime"] == "2026-10-25T03:15:00+02:00"
    daily = _build(points, daily=True)
    assert len(daily) == 1
    assert daily[0]["datetime"] == "2026-10-25T00:00:00+03:00"


def test_dst_spring_forward_and_local_day_midnight():
    points = [
        _point("2027-03-28T00:30:00+00:00", temperature=1),
        _point("2027-03-28T01:30:00+00:00", temperature=4),
    ]
    hourly = _build(points)
    assert [p["datetime"] for p in hourly] == [
        "2027-03-28T02:30:00+02:00",
        "2027-03-28T04:30:00+03:00",
    ]
    assert _build(points, daily=True)[0]["datetime"] == (
        "2027-03-28T00:00:00+02:00"
    )


def test_daily_precipitation_is_only_summed_for_hourly_samples():
    points = [
        _point("2026-12-30T07:00:00+00:00", precipitation=0.2),
        _point("2026-12-30T08:00:00+00:00", precipitation=0.0),
        _point("2026-12-30T09:00:00+00:00", precipitation=0.7),
    ]
    hourly = _build(points, daily=True)
    sparse = _build(points, daily=True, hourly_precipitation=False)
    assert hourly[0]["native_precipitation"] == pytest.approx(0.9)
    assert sparse[0]["native_precipitation"] is None


def test_daily_max_min_ignore_missing_and_nonfinite_values():
    points = [
        _point("2026-12-30T07:00:00+00:00", temperature=None, precipitation=None),
        _point("2026-12-30T08:00:00+00:00", temperature=math.nan,
               precipitation=math.inf),
        _point("2026-12-30T09:00:00+00:00", temperature=-4, precipitation=0),
        _point("2026-12-30T10:00:00+00:00", temperature=7, precipitation=0.4),
    ]
    day = _build(points, daily=True)[0]
    assert day["native_temperature"] == 7
    assert day["native_templow"] == -4
    assert day["native_precipitation"] == 0.4
    assert _build(points)[0]["native_temperature"] is None
    assert _build(points)[1]["native_precipitation"] is None


def test_missing_temperatures_and_precipitation_remain_none():
    points = [
        _point("2026-12-30T09:00:00+00:00", temperature=None,
               precipitation=None, symbol=None),
        _point("2026-12-30T10:00:00+00:00", temperature=math.nan,
               precipitation=math.nan),
    ]
    day = _build(points, daily=True)[0]
    assert day["native_temperature"] is None
    assert day["native_templow"] is None
    assert day["native_precipitation"] is None


def test_daily_condition_uses_nearest_local_noon_not_first_item():
    points = [
        _point("2026-12-30T03:00:00+00:00", symbol=21),
        _point("2026-12-30T10:00:00+00:00", symbol=3),
        _point("2026-12-30T17:00:00+00:00", symbol=1),
    ]
    assert _build(points, daily=True)[0]["condition"] == "symbol-3"


def test_discard_expired_naive_and_duplicate_slots():
    first = _point("2026-12-30T10:00:00+00:00", temperature=1)
    latest = _point("2026-12-30T12:00:00+02:00", temperature=2)
    expired = _point("2026-10-22T09:00:00+00:00", temperature=12)
    naive = _point("2026-12-30T13:00:00", temperature=13)
    actual = _build([first, latest, expired, naive])
    assert len(actual) == 1
    assert actual[0]["native_temperature"] == 2


def test_empty_and_missing_forecasts():
    assert _build([]) == []
    assert _build(None, daily=True) == []


def test_reference_time_must_be_timezone_aware():
    with pytest.raises(ValueError, match="timezone-aware"):
        _build([], now=datetime(2026, 12, 1))


def test_one_day_temperature_extremes_not_copied_from_adjacent_day():
    points = [
        _point("2026-12-30T21:00:00+00:00", temperature=-3),
        _point("2026-12-30T22:00:00+00:00", temperature=15),
    ]
    days = _build(points, daily=True)
    assert len(days) == 2
    assert days[0]["native_templow"] == -3
    assert days[1]["native_temperature"] == 15
