"""Check installed FMI client v1 public API, without mocking the library.

Existing HA lifecycle tests intentionally mock FMI responses, so they cannot
detect renamed third-party exports or changed call signatures by themselves.
"""

import inspect
from datetime import UTC, datetime, timedelta
from importlib.metadata import version

import fmi_weather_client as fmi
import pytest
from fmi_weather_client import errors, models

EXPECTED_VERSION = "1.0.0"

REQUIRED_WEATHER_FIELDS = {
    "time",
    "symbol",
    "temperature",
    "humidity",
    "wind_speed",
    "wind_gust",
    "wind_direction",
    "pressure",
    "cloud_cover",
    "dew_point",
    "precipitation_amount",
}


def _model_field_names(model):
    """Support dataclasses, Pydantic versions and regular annotated models."""
    result = set(getattr(model, "__annotations__", {}))
    result.update(getattr(model, "__dataclass_fields__", {}))
    result.update(getattr(model, "model_fields", {}))
    result.update(getattr(model, "__fields__", {}))
    return result


def test_pinned_client_is_installed():
    assert version("fmi-weather-client") == EXPECTED_VERSION


def test_public_async_client_functions_accept_existing_calls():
    """Exercise the same argument counts used by the live FMI integration."""
    expected = {
        "async_weather_by_coordinates": (60.17, 24.94),
        "async_forecast_by_coordinates": (60.17, 24.94, 1, 24),
        "async_observation_by_station_id": (101,),
    }
    for function_name, args in expected.items():
        func = getattr(fmi, function_name)
        assert inspect.iscoroutinefunction(func), function_name
        inspect.signature(func).bind(*args)


def test_client_error_types_exist():
    assert issubclass(errors.ClientError, Exception)
    assert issubclass(errors.ServerError, Exception)


def test_models_retain_weather_fields_expected_by_entities():
    """Avoid passing fake objects that mask real-world schema regressions."""
    assert isinstance(models.Weather, type)
    assert isinstance(models.Forecast, type)
    assert isinstance(models.WeatherData, type)

    assert {"place", "data"} <= _model_field_names(models.Weather)
    assert {"forecasts"} <= _model_field_names(models.Forecast)
    assert REQUIRED_WEATHER_FIELDS <= _model_field_names(models.WeatherData)


@pytest.mark.asyncio
async def test_real_v1_model_instances_drive_native_ha_entities(
    hass, make_entry, mock_api
):
    """Mock transport only; exercise real v1 model objects in entity mapping."""
    now = datetime.now(UTC).replace(microsecond=0)

    def data_at(when, temperature):
        values = {
            name: models.Value(None, "")
            for name in models.WeatherData._fields
            if name != "time"
        }
        values.update(
            time=when,
            temperature=models.Value(temperature, "°C"),
            dew_point=models.Value(1.0, "°C"),
            humidity=models.Value(70.0, "%"),
            wind_speed=models.Value(4.0, "m/s"),
            wind_gust=models.Value(6.0, "m/s"),
            wind_max=models.Value(6.0, "m/s"),
            wind_direction=models.Value(180.0, "°"),
            pressure=models.Value(1011.0, "hPa"),
            symbol=models.Value(2, ""),
            cloud_cover=models.Value(40.0, "%"),
            precipitation_amount=models.Value(0.2, "mm"),
        )
        return models.WeatherData(**values)

    current = models.Weather("Helsinki", 60.17, 24.94, data_at(now, 5.0))
    tomorrow = data_at(now + timedelta(hours=2), 7.0)
    forecast = models.Forecast("Helsinki", 60.17, 24.94, [tomorrow])
    mock_api.weather.return_value = current
    mock_api.forecast.return_value = forecast

    entry = make_entry(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.coordinator.last_update_success

    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    temperature = registry.async_get_entity_id(
        "sensor", "fmi", "60.17:24.94_Home_Temperature"
    )
    assert temperature is not None
    state = hass.states.get(temperature)
    assert float(state.state) == pytest.approx(5.0)
    assert state.attributes["unit_of_measurement"] == "°C"
