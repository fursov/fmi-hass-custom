"""Behavioral baseline of the unmodified weather forecast transformation."""

import asyncio
import math
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tests.conftest import source_definition

FORECAST_KEYS = {
    "ATTR_FORECAST_TIME": "datetime",
    "ATTR_FORECAST_CONDITION": "condition",
    "ATTR_FORECAST_NATIVE_TEMP": "temperature",
    "ATTR_FORECAST_NATIVE_TEMP_LOW": "templow",
    "ATTR_FORECAST_NATIVE_PRECIPITATION": "precipitation",
    "ATTR_FORECAST_NATIVE_WIND_SPEED": "wind_speed",
    "ATTR_FORECAST_WIND_BEARING": "wind_bearing",
    "ATTR_WEATHER_PRESSURE": "pressure",
    "ATTR_WEATHER_HUMIDITY": "humidity",
    "ATTR_FORECAST_CLOUD_COVERAGE": "cloud_coverage",
}


def _weather_point(raw):
    names = (
        "temperature",
        "precipitation_amount",
        "wind_speed",
        "wind_direction",
        "pressure",
        "humidity",
        "cloud_cover",
    )
    fields = {name: SimpleNamespace(value=raw[name]) for name in names}
    return SimpleNamespace(
        **fields,
        time=datetime.fromisoformat(raw["time"]),
        symbol=SimpleNamespace(value=raw["symbol"]),
    )


def _entity(payload, *, daily_mode=False):
    utils = SimpleNamespace(get_weather_symbol=lambda symbol: f"symbol-{symbol}")
    scope = {
        "Forecast": dict,
        "math": math,
        "tz": SimpleNamespace(tzlocal=lambda: UTC),
        "utils": utils,
        **FORECAST_KEYS,
    }
    Weather = source_definition(
        "weather.py",
        "FMIWeatherEntity",
        methods=[
            "_forecast",
            "__get_value",
            "async_forecast_hourly",
            "async_forecast_daily",
        ],
        namespace=scope,
        base="object",
    )
    coordinator = SimpleNamespace(
        get_forecasts=lambda: [_weather_point(item) for item in payload["forecasts"]]
    )
    entity = Weather()
    entity.coordinator = coordinator
    entity._daily_mode = daily_mode
    return entity


def test_hourly_baseline_preserves_slots_and_values(forecast_payload):
    entity = _entity(forecast_payload)
    hourly = asyncio.run(entity.async_forecast_hourly())
    assert len(hourly) == 3
    assert [point["temperature"] for point in hourly] == [2.0, 4.0, 1.0]
    assert [point["precipitation"] for point in hourly] == [0.2, 0.7, 0.1]
    assert all(datetime.fromisoformat(point["datetime"]).tzinfo for point in hourly)


def test_daily_baseline_has_high_and_low(forecast_payload):
    entity = _entity(forecast_payload)
    daily = asyncio.run(entity.async_forecast_daily())
    assert len(daily) == 2
    assert daily[0]["temperature"] == 4.0
    assert daily[0]["templow"] == 2.0
    assert daily[1]["temperature"] == 1.0


@pytest.mark.xfail(strict=True, reason="PR4: daily precipitation is not aggregated")
def test_daily_precipitation_should_sum_hourly_amounts(forecast_payload):
    entity = _entity(forecast_payload)
    daily = asyncio.run(entity.async_forecast_daily())
    assert daily[0]["precipitation"] == pytest.approx(0.9)


@pytest.mark.xfail(
    strict=True, reason="PR4: daily entity returns daily data from hourly method"
)
def test_hourly_contract_independent_of_daily_entity_flag(forecast_payload):
    entity = _entity(forecast_payload, daily_mode=True)
    hourly = asyncio.run(entity.async_forecast_hourly())
    assert len(hourly) == 3


def test_empty_forecast_returns_empty_list(forecast_payload):
    entity = _entity({**forecast_payload, "forecasts": []})
    assert asyncio.run(entity.async_forecast_hourly()) == []
