"""Behavioral baseline of the unmodified weather forecast transformation."""

import asyncio
import importlib.util
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from conftest import ROOT, source_definition


def _forecast_builder():
    """Import the pure helper without importing the HA integration package."""
    spec = importlib.util.spec_from_file_location(
        "fmi_forecast_offline", ROOT / "forecast.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.build_forecast


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
        "build_forecast": _forecast_builder(),
        "dt_util": SimpleNamespace(as_local=lambda value: value.astimezone(UTC)),
        "utils": utils,
    }
    Weather = source_definition(
        "weather.py",
        "FMIWeatherEntity",
        methods=[
            "_forecast",
            "async_forecast_hourly",
            "async_forecast_daily",
        ],
        namespace=scope,
        base="object",
    )
    coordinator = SimpleNamespace(
        get_forecasts=lambda: [_weather_point(item) for item in payload["forecasts"]],
        time_step=1,
    )
    entity = Weather()
    entity.coordinator = coordinator
    entity._daily_mode = daily_mode
    return entity


def test_hourly_baseline_preserves_slots_and_values(forecast_payload):
    entity = _entity(forecast_payload)
    hourly = asyncio.run(entity.async_forecast_hourly())
    assert len(hourly) == 3
    assert [point["native_temperature"] for point in hourly] == [2.0, 4.0, 1.0]
    assert [point["native_precipitation"] for point in hourly] == [0.2, 0.7, 0.1]
    assert all(datetime.fromisoformat(point["datetime"]).tzinfo for point in hourly)


def test_daily_baseline_has_high_and_low(forecast_payload):
    entity = _entity(forecast_payload)
    daily = asyncio.run(entity.async_forecast_daily())
    assert len(daily) == 2
    assert daily[0]["native_temperature"] == 4.0
    assert daily[0]["native_templow"] == 2.0
    assert daily[1]["native_temperature"] == 1.0


def test_daily_precipitation_should_sum_hourly_amounts(forecast_payload):
    entity = _entity(forecast_payload)
    daily = asyncio.run(entity.async_forecast_daily())
    assert daily[0]["native_precipitation"] == pytest.approx(0.9)


def test_hourly_contract_independent_of_daily_entity_flag(forecast_payload):
    entity = _entity(forecast_payload, daily_mode=True)
    hourly = asyncio.run(entity.async_forecast_hourly())
    assert len(hourly) == 3
    assert "native_templow" not in hourly[0]


def test_empty_forecast_returns_empty_list(forecast_payload):
    entity = _entity({**forecast_payload, "forecasts": []})
    assert asyncio.run(entity.async_forecast_hourly()) == []
