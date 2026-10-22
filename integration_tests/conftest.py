
"""Runtime Home Assistant integration-test fixtures (no FMI network access)."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from pytest_homeassistant_custom_component.common import MockConfigEntry

from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_NAME

DOMAIN = "fmi"
DATA = {
    CONF_NAME: "Home",
    CONF_LATITUDE: 60.17,
    CONF_LONGITUDE: 24.94,
}


@pytest.fixture(autouse=True)
def enable_fmi_integration(enable_custom_integrations):
    """Ensure the staged custom integration overrides the built-in FMI domain."""
    _ = enable_custom_integrations


@pytest.fixture
def make_entry():
    """Create a genuine HA config entry using the original persisted options."""

    def create(hass, *, options=None, unique_id="60.17_24.94"):
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Helsinki",
            unique_id=unique_id,
            data=DATA,
            options=options or {},
        )
        entry.add_to_hass(hass)
        return entry

    return create


def _reading(value, unit=None):
    return SimpleNamespace(value=value, unit=unit)


def _observation(now, *, temperature=5.0, symbol=2):
    data = SimpleNamespace(
        time=now,
        symbol=_reading(symbol),
        temperature=_reading(temperature, "°C"),
        humidity=_reading(70, "%"),
        wind_speed=_reading(4.0, "m/s"),
        wind_gust=_reading(6.0, "m/s"),
        wind_max=_reading(6.0, "m/s"),
        wind_direction=_reading(180, "°"),
        pressure=_reading(1011, "hPa"),
        cloud_cover=_reading(40, "%"),
        dew_point=_reading(1.0, "°C"),
        precipitation_amount=_reading(0.2, "mm/h"),
    )
    return SimpleNamespace(place="Helsinki", data=data)


@pytest.fixture
def mock_api():
    """Mock only FMI providers and the optional external services, not HA internals.

    Patching the imported third-party client leaves the real FMI coordinator,
    SensorEntity, WeatherEntity, ConfigEntry and registries in play.
    """
    from custom_components.fmi import FMIDataUpdateCoordinator

    now = datetime.now(timezone.utc).replace(microsecond=0)
    current = _observation(now)
    observation = _observation(now, temperature=8.0)
    point_a = _observation(now + timedelta(hours=1)).data
    point_b = _observation(now + timedelta(hours=2), temperature=7.0).data
    forecast = SimpleNamespace(forecasts=[point_a, point_b])

    with (
        patch(
            "custom_components.fmi.fmi.async_weather_by_coordinates",
            new_callable=AsyncMock,
            return_value=current,
        ) as weather_api,
        patch(
            "custom_components.fmi.fmi.async_forecast_by_coordinates",
            new_callable=AsyncMock,
            return_value=forecast,
        ) as forecast_api,
        patch(
            "custom_components.fmi.fmi.async_observation_by_station_id",
            new_callable=AsyncMock,
            return_value=observation,
        ) as station_api,
        patch.object(
            FMIDataUpdateCoordinator,
            "_FMIDataUpdateCoordinator__update_mareo_data",
            return_value=None,
        ),
        patch("custom_components.fmi.Nominatim", return_value=Mock()),
    ):
        yield SimpleNamespace(
            weather=weather_api,
            forecast=forecast_api,
            station=station_api,
            current=current,
            observation=observation,
        )
