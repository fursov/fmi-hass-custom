"""Offline regression tests for FMI coordinator and entity listener lifecycle.

Only selected source definitions are evaluated: no Home Assistant import, API
requests, or live FMI connection is required. These tests model the public
CoordinatorEntity subscription lifecycle and coordinator refresh contract.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from conftest import source_definition


class FakeUpdateFailed(Exception):
    """Stand-in for the HA coordinator update exception."""


class FakeDataUpdateCoordinator:
    """Model HA's return-data-driven refresh and listener notification."""

    def __init__(self):
        self.listeners = []
        self.last_update_success = True
        self.data = None
        self.manual_updates = 0

    def async_add_listener(self, callback, context=None):
        self.listeners.append(callback)

        def unsubscribe():
            self.listeners.remove(callback)

        return unsubscribe

    def async_set_updated_data(self, data):
        self.manual_updates += 1
        self.data = data
        self._notify()

    def _notify(self):
        for listener in list(self.listeners):
            listener()

    async def async_refresh(self):
        data = await self._async_update_data()
        self.data = data
        self._notify()

    def get_weather(self):
        return None

    def get_observation(self):
        return None

    def get_current_place(self):
        return "Helsinki"


class FakeCoordinatorEntity:
    """Model HA CoordinatorEntity's managed subscription on add/remove."""

    def __init__(self, coordinator):
        self.coordinator = coordinator
        self.hass = SimpleNamespace(async_create_task=lambda coro: coro.close())
        self.writes = 0
        self._unsubscribe = None

    async def async_added_to_hass(self):
        self._unsubscribe = self.coordinator.async_add_listener(
            self._handle_coordinator_update
        )

    async def async_will_remove_from_hass(self):
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None

    def _handle_coordinator_update(self):
        self.async_write_ha_state()

    def async_write_ha_state(self):
        self.writes += 1


@asynccontextmanager
async def noop_timeout(_seconds):
    yield


class FakeHass:
    async def async_add_executor_job(self, callback):
        callback()


def _data_coordinator_class(name="FMIDataUpdateCoordinator"):
    return source_definition(
        "__init__.py",
        name,
        methods=["_async_update_data", "_refresh_optional_source"],
        base="DataUpdateCoordinator",
        namespace={
            "DataUpdateCoordinator": FakeDataUpdateCoordinator,
            "UpdateFailed": FakeUpdateFailed,
            "timeout": noop_timeout,
            "const": SimpleNamespace(
                TIMEOUT_FMI_INTEG_IN_SEC=40,
                TIMEOUT_OPTIONAL_SOURCE_IN_SEC=40,
                CURRENT_MAX_AGE=timedelta(hours=3),
                OBSERVATION_MAX_AGE=timedelta(hours=2),
                BEST_CONDITION_NOT_AVAIL="not_available",
            ),
            "is_fresh_weather": lambda weather, *_args, **_kwargs: weather is not None,
            "timedelta": timedelta,
        },
    )


def test_forecast_refresh_emits_one_notification_after_all_data_is_ready():
    Coordinator = _data_coordinator_class()
    coordinator = Coordinator()
    FakeDataUpdateCoordinator.__init__(coordinator)
    coordinator.logger = logging.getLogger("test.fmi")
    coordinator._hass = FakeHass()
    coordinator.current = None
    coordinator.lightning_mode = False
    coordinator.lightning_radius = 0
    events = []
    current = object()

    async def fetch_current():
        events.append("current")
        return current

    async def fetch_forecast():
        events.append("forecast")

    coordinator._fetch_forecast_weather = fetch_current
    coordinator._fetch_forecast = fetch_forecast
    coordinator._FMIDataUpdateCoordinator__update_best_weather_condition = (
        lambda: events.append("best")
    )
    coordinator._FMIDataUpdateCoordinator__update_mareo_data = (
        lambda: events.append("sea_level")
    )
    coordinator.async_add_listener(lambda: events.append("published"))

    asyncio.run(coordinator.async_refresh())

    assert coordinator.data == {"current": current}
    assert coordinator.manual_updates == 0
    assert events == ["current", "forecast", "best", "sea_level", "published"]


def test_failed_forecast_refresh_never_publishes_empty_data():
    Coordinator = _data_coordinator_class()
    coordinator = Coordinator()
    FakeDataUpdateCoordinator.__init__(coordinator)
    coordinator.logger = logging.getLogger("test.fmi")
    coordinator._hass = FakeHass()
    coordinator._fetch_forecast_weather = AsyncMock(return_value=None)
    events = []
    coordinator.async_add_listener(lambda: events.append("published"))

    with pytest.raises(FakeUpdateFailed, match="missing or stale"):
        asyncio.run(coordinator.async_refresh())

    assert events == []
    assert coordinator.manual_updates == 0


def test_observation_refresh_returns_current_station_data_once():
    Coordinator = _data_coordinator_class("FMIObservationUpdateCoordinator")
    coordinator = Coordinator()
    FakeDataUpdateCoordinator.__init__(coordinator)
    coordinator.logger = logging.getLogger("test.fmi")
    coordinator.observation_station_id = 101
    station_data = object()

    async def fetch_observation():
        coordinator.observation = station_data

    coordinator._fetch_observation = fetch_observation
    events = []
    coordinator.async_add_listener(lambda: events.append("published"))
    asyncio.run(coordinator.async_refresh())

    assert coordinator.data == {"observation": station_data}
    assert coordinator.manual_updates == 0
    assert events == ["published"]


def _weather_entity_class():
    const = SimpleNamespace(
        LOGGER=logging.getLogger("test.fmi"),
        DOMAIN="fmi",
        NAME="FMI",
        MANUFACTURER="Finnish Meteorological Institute",
        ATTRIBUTION="Weather Data provided by FMI",
    )
    Weather = source_definition(
        "weather.py",
        "FMIWeatherEntity",
        methods=["__init__", "_handle_coordinator_update"],
        base="CoordinatorEntity",
        namespace={
            "CoordinatorEntity": FakeCoordinatorEntity,
            "FMIDataUpdateCoordinator": FakeDataUpdateCoordinator,
            "const": const,
            "DeviceEntryType": SimpleNamespace(SERVICE="service"),
            "WeatherEntityFeature": int,
            "ha_core": SimpleNamespace(callback=lambda function: function),
        },
    )
    Weather.update_callback = lambda self: setattr(
        self, "updates", getattr(self, "updates", 0) + 1
    )

    async def ignore_forecast_updates(self, forecast_types):
        _ = forecast_types

    Weather.async_update_listeners = ignore_forecast_updates
    return Weather


def _sensor_entity_class():
    Sensor = source_definition(
        "sensor.py",
        "_BaseSensorClass",
        methods=["__init__", "_handle_coordinator_update"],
        base="CoordinatorEntity",
        namespace={
            "CoordinatorEntity": FakeCoordinatorEntity,
            "FMIDataUpdateCoordinator": FakeDataUpdateCoordinator,
            "const": SimpleNamespace(
                LOGGER=logging.getLogger("test.fmi"),
                ATTRIBUTION="Weather Data provided by FMI",
            ),
            "ha_const": SimpleNamespace(STATE_UNAVAILABLE="unavailable"),
            "ha_core": SimpleNamespace(callback=lambda function: function),
        },
    )
    Sensor.update = lambda self: setattr(
        self, "updates", getattr(self, "updates", 0) + 1
    )
    Sensor.update_callback = Sensor.update
    return Sensor


@pytest.mark.parametrize("platform", ["weather", "sensor"])
def test_entity_only_subscribes_while_added_and_writes_once(platform):
    coordinator = FakeDataUpdateCoordinator()
    coordinator.unique_id = "60.17:24.94"
    if platform == "weather":
        entity = _weather_entity_class()("Home", coordinator)
    else:
        entity = _sensor_entity_class()(
            "Home", coordinator, 1, ["Temperature", "°C", "mdi:thermometer"]
        )
    assert coordinator.listeners == []
    initial_updates = entity.updates
    asyncio.run(entity.async_added_to_hass())
    assert len(coordinator.listeners) == 1

    coordinator._notify()
    assert entity.updates == initial_updates + 1
    assert entity.writes == 1

    asyncio.run(entity.async_will_remove_from_hass())
    assert coordinator.listeners == []
    coordinator._notify()
    assert entity.updates == initial_updates + 1
    assert entity.writes == 1


def test_weather_observation_entity_subscribes_through_own_coordinator():
    forecast = FakeDataUpdateCoordinator()
    observation = FakeDataUpdateCoordinator()
    forecast.unique_id = "60.17:24.94"
    observation.unique_id = "60.17:24.94_observation"
    Weather = _weather_entity_class()
    forecast_entity = Weather("Home", forecast)
    observation_entity = Weather("Home", observation, station_id=True)

    asyncio.run(forecast_entity.async_added_to_hass())
    asyncio.run(observation_entity.async_added_to_hass())
    forecast._notify()
    assert forecast_entity.writes == 1
    assert observation_entity.writes == 0
    observation._notify()
    assert observation_entity.writes == 1

    asyncio.run(forecast_entity.async_will_remove_from_hass())
    asyncio.run(observation_entity.async_will_remove_from_hass())
    assert not forecast.listeners
    assert not observation.listeners


def test_weather_forecast_subscribers_receive_updates_after_state_change():
    """Weather forecast subscriptions are distinct from coordinator listeners."""
    coordinator = FakeDataUpdateCoordinator()
    coordinator.unique_id = "60.17:24.94"
    Weather = _weather_entity_class()
    entity = Weather("Home", coordinator)
    queued = []
    pushed = []

    async def capture_forecasts(forecast_types):
        pushed.append(tuple(forecast_types))

    entity.async_update_listeners = capture_forecasts
    entity.hass = SimpleNamespace(async_create_task=queued.append)
    asyncio.run(entity.async_added_to_hass())
    coordinator._notify()
    assert entity.writes == 1
    assert len(queued) == 1
    assert pushed == []
    asyncio.run(queued.pop())
    assert pushed == [("hourly", "daily")]
    asyncio.run(entity.async_will_remove_from_hass())


def test_observation_weather_does_not_advertise_or_push_forecasts():
    coordinator = FakeDataUpdateCoordinator()
    coordinator.unique_id = "60.17:24.94_observation"
    Weather = _weather_entity_class()
    entity = Weather("Home", coordinator, station_id=True)
    queued = []
    entity.hass = SimpleNamespace(async_create_task=queued.append)
    assert entity._attr_supported_features == 0
    asyncio.run(entity.async_added_to_hass())
    coordinator._notify()
    assert entity.writes == 1
    assert queued == []
    asyncio.run(entity.async_will_remove_from_hass())
