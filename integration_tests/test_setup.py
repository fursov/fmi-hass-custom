"""End-to-end FMI integration tests against a real Home Assistant fixture."""

from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er

DOMAIN = "fmi"


async def _setup(hass, make_entry, mock_api, options=None):
    """Load real coordinator and platforms with only network services mocked."""
    _ = mock_api
    entry = make_entry(hass, options=options)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


@pytest.mark.asyncio
async def test_setup_registers_native_sensors_and_weather(hass, make_entry, mock_api):
    """The real entity registry must preserve all historic identifiers."""
    entry = await _setup(hass, make_entry, mock_api)
    registry = er.async_get(hass)

    temperature = registry.async_get_entity_id(
        "sensor", DOMAIN, "60.17:24.94_Home_Temperature"
    )
    rain = registry.async_get_entity_id(
        "sensor", DOMAIN, "60.17:24.94_Home_Rain"
    )
    weather = registry.async_get_entity_id(
        "weather", DOMAIN, "60.17:24.94"
    )

    assert temperature is not None
    assert rain is not None
    assert weather is not None
    assert float(hass.states.get(temperature).state) == pytest.approx(5.0)
    assert hass.states.get(temperature).attributes["unit_of_measurement"] == "°C"
    assert float(hass.states.get(rain).state) == pytest.approx(0.2)
    assert hass.states.get(weather).state == "partlycloudy"
    assert entry.runtime_data.coordinator.last_update_success
    mock_api.weather.assert_awaited()


@pytest.mark.asyncio
async def test_daily_and_station_entities_keep_old_identifiers(
    hass, make_entry, mock_api
):
    """Options keep existing additional weather entities in registry."""
    entry = await _setup(
        hass, make_entry, mock_api,
        options={"daily_mode": True, "observation_station_id": 101},
    )
    registry = er.async_get(hass)
    daily = registry.async_get_entity_id(
        "weather", DOMAIN, "60.17:24.94_daily"
    )
    station = registry.async_get_entity_id(
        "weather", DOMAIN, "60.17:24.94_observation_observation"
    )
    assert daily is not None
    assert station is not None
    assert entry.runtime_data.observation is not None
    assert entry.runtime_data.observation.last_update_success
    assert hass.states.get(daily) is not None
    assert hass.states.get(station) is not None
    mock_api.station.assert_awaited_once_with(101)


@pytest.mark.asyncio
async def test_get_forecasts_service_and_empty_optional_forecast(
    hass, make_entry, mock_api
):
    """Exercise real weather.get_forecasts service, not only a helper method."""
    entry = await _setup(hass, make_entry, mock_api)
    registry = er.async_get(hass)
    weather_id = registry.async_get_entity_id(
        "weather", DOMAIN, "60.17:24.94"
    )
    assert weather_id is not None

    hourly = await hass.services.async_call(
        "weather", "get_forecasts",
        {"entity_id": weather_id, "type": "hourly"},
        blocking=True, return_response=True,
    )
    assert len(hourly[weather_id]["forecast"]) == 2

    daily = await hass.services.async_call(
        "weather", "get_forecasts",
        {"entity_id": weather_id, "type": "daily"},
        blocking=True, return_response=True,
    )
    assert len(daily[weather_id]["forecast"]) >= 1

    mock_api.forecast.return_value = None
    await entry.runtime_data.coordinator.async_refresh()
    await hass.async_block_till_done()

    unavailable = await hass.services.async_call(
        "weather", "get_forecasts",
        {"entity_id": weather_id, "type": "hourly"},
        blocking=True, return_response=True,
    )
    assert unavailable[weather_id]["forecast"] == []


@pytest.mark.asyncio
async def test_reload_and_unload_restore_entity_registry_and_listeners(
    hass, make_entry, mock_api
):
    """HA should not keep stale subscriptions when the config entry reloads."""
    entry = await _setup(hass, make_entry, mock_api)
    registry = er.async_get(hass)
    sensor_id = registry.async_get_entity_id(
        "sensor", DOMAIN, "60.17:24.94_Home_Temperature"
    )
    coordinator = entry.runtime_data.coordinator
    assert sensor_id is not None
    assert hass.states.get(sensor_id) is not None

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.coordinator is not coordinator
    assert hass.states.get(sensor_id) is not None

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    # HA may retain a restored placeholder while no integration is loaded.
    unloaded = hass.states.get(sensor_id)
    assert unloaded is None or unloaded.state == "unavailable"

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get(sensor_id) is not None


@pytest.mark.asyncio
async def test_station_outage_does_not_block_weather_entities(
    hass, make_entry, mock_api
):
    """An optional station outage is isolated from the main FMI coordinator."""
    mock_api.station.side_effect = OSError("synthetic station outage")
    await _setup(
        hass, make_entry, mock_api, options={"observation_station_id": 101}
    )
    registry = er.async_get(hass)
    weather = registry.async_get_entity_id(
        "weather", DOMAIN, "60.17:24.94"
    )
    station = registry.async_get_entity_id(
        "weather", DOMAIN, "60.17:24.94_observation_observation"
    )
    assert weather is not None
    assert station is not None
    assert hass.states.get(weather).state == "partlycloudy"
    assert hass.states.get(station).state == "unavailable"


@pytest.mark.asyncio
async def test_initial_core_outage_retries_setup(hass, make_entry, mock_api):
    """No stale entities may appear when core FMI weather cannot be fetched."""
    mock_api.weather.return_value = None
    entry = make_entry(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY
    registry = er.async_get(hass)
    assert registry.async_get_entity_id(
        "weather", DOMAIN, "60.17:24.94"
    ) is None


@pytest.mark.asyncio
async def test_options_update_preserves_entry_and_entities(
    hass, make_entry, mock_api
):
    """The actual options-update listener must reload without changing IDs."""
    entry = await _setup(hass, make_entry, mock_api)
    registry = er.async_get(hass)
    sensor_id = registry.async_get_entity_id(
        "sensor", DOMAIN, "60.17:24.94_Home_Temperature"
    )
    first = entry.runtime_data.coordinator
    with patch(
        "custom_components.fmi.fmi.async_forecast_by_coordinates",
        mock_api.forecast,
    ):
        hass.config_entries.async_update_entry(
            entry, options={"forecast_days": 2, "offset": 3}
        )
        await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.coordinator is not first
    assert registry.async_get_entity_id(
        "sensor", DOMAIN, "60.17:24.94_Home_Temperature"
    ) == sensor_id
    assert entry.options["forecast_days"] == 2
