"""Offline characterization of partial FMI failures and data freshness."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from conftest import source_definition


class ClientError(Exception):
    """Fake FMI client error."""


class ServerError(Exception):
    """Fake FMI server error."""


class UpdateFailed(Exception):
    """Fake coordinator update failure."""


class ConfigEntryNotReady(Exception):
    """Fake Home Assistant setup retry exception."""


NOW = datetime(2026, 10, 22, 11, 0, tzinfo=UTC)


def fresh_weather():
    return source_definition(
        "__init__.py",
        "is_fresh_weather",
        namespace={
            "datetime": datetime,
            "timezone": SimpleNamespace(utc=UTC),
            "timedelta": timedelta,
        },
    )


def future_forecast():
    return source_definition(
        "__init__.py",
        "has_future_forecast",
        namespace={
            "datetime": datetime,
            "timezone": SimpleNamespace(utc=UTC),
        },
    )


def point(timestamp):
    return SimpleNamespace(time=timestamp)


def forecast_at(*times):
    return SimpleNamespace(forecasts=[point(stamp) for stamp in times])


@pytest.mark.parametrize(
    ("timestamp", "is_valid"),
    [
        (NOW - timedelta(hours=2), True),
        (NOW - timedelta(hours=3), True),
        (NOW - timedelta(hours=3, seconds=1), False),
        (NOW + timedelta(hours=1), True),
        (NOW + timedelta(hours=2, seconds=1), False),
        (NOW.replace(tzinfo=None), False),
        (None, False),
    ],
)
def test_current_freshness_boundaries(timestamp, is_valid):
    weather = SimpleNamespace(data=SimpleNamespace(time=timestamp))
    assert fresh_weather()(weather, timedelta(hours=3), now=NOW) is is_valid


def test_missing_weather_is_not_fresh():
    assert not fresh_weather()(None, timedelta(hours=3), now=NOW)


def test_observation_has_tighter_future_tolerance():
    station = SimpleNamespace(data=SimpleNamespace(time=NOW + timedelta(minutes=16)))
    assert not fresh_weather()(
        station, timedelta(hours=2), max_future=timedelta(minutes=15), now=NOW
    )


@pytest.mark.parametrize(
    ("times", "expected"),
    [
        ([], False),
        ([NOW - timedelta(hours=1)], False),
        ([NOW - timedelta(hours=1), NOW + timedelta(hours=1)], True),
        ([NOW], False),
        ([NOW.replace(tzinfo=None)], False),
    ],
)
def test_only_future_forecast_points_count(times, expected):
    assert future_forecast()(forecast_at(*times), now=NOW) is expected


def _forecast_coordinator(api):
    import typing

    Coordinator = source_definition(
        "__init__.py",
        "FMIDataUpdateCoordinator",
        methods=["_fetch_forecast", "get_forecasts"],
        base="object",
        namespace={
            "timeout": asyncio.timeout,
            "const": SimpleNamespace(TIMEOUT_OPTIONAL_FORECAST_IN_SEC=2),
            "fmi": SimpleNamespace(async_forecast_by_coordinates=api),
            "fmi_erros": SimpleNamespace(ClientError=ClientError, ServerError=ServerError),
            "has_future_forecast": future_forecast(),
            "typing": typing,
            "fmi_models": SimpleNamespace(WeatherData=object),
        },
    )
    coordinator = Coordinator()
    coordinator.latitude = 60.17
    coordinator.longitude = 24.94
    coordinator.time_step = 1
    coordinator.forecast_points = 3
    coordinator.logger = logging.getLogger("fmi.test.forecast")
    coordinator.forecast = None
    return coordinator


def test_forecast_failure_clears_old_snapshot_and_recovers():
    valid = forecast_at(datetime.now(UTC) + timedelta(hours=2))
    api = AsyncMock(side_effect=[ClientError("service down"), valid])
    coordinator = _forecast_coordinator(api)
    coordinator.forecast = valid

    asyncio.run(coordinator._fetch_forecast())
    assert coordinator.forecast is None
    assert coordinator.get_forecasts() == []

    asyncio.run(coordinator._fetch_forecast())
    assert coordinator.forecast is valid
    assert coordinator.get_forecasts() == valid.forecasts


def test_expired_or_disabled_forecast_cannot_remain_visible():
    expired = forecast_at(datetime.now(UTC) - timedelta(minutes=5))
    api = AsyncMock(return_value=expired)
    coordinator = _forecast_coordinator(api)
    asyncio.run(coordinator._fetch_forecast())
    assert coordinator.forecast is None

    coordinator.forecast = forecast_at(datetime.now(UTC) + timedelta(hours=2))
    coordinator.forecast_points = 0
    asyncio.run(coordinator._fetch_forecast())
    assert coordinator.forecast is None
    assert api.await_count == 1


class FakeHass:
    async def async_add_executor_job(self, callback):
        return callback()


def _core_coordinator():
    Coordinator = source_definition(
        "__init__.py",
        "FMIDataUpdateCoordinator",
        methods=["_async_update_data", "_refresh_optional_source"],
        base="object",
        namespace={
            "timeout": asyncio.timeout,
            "const": SimpleNamespace(
                TIMEOUT_FMI_INTEG_IN_SEC=2,
                TIMEOUT_OPTIONAL_SOURCE_IN_SEC=2,
                CURRENT_MAX_AGE=timedelta(hours=3),
                BEST_CONDITION_NOT_AVAIL="not_available",
            ),
            "UpdateFailed": UpdateFailed,
            "is_fresh_weather": fresh_weather(),
        },
    )
    coordinator = Coordinator()
    coordinator.logger = logging.getLogger("fmi.test.current")
    coordinator._hass = FakeHass()
    coordinator.current = None
    coordinator.lightning_mode = True
    coordinator.lightning_radius = 200
    coordinator._fetch_forecast = AsyncMock()
    coordinator._FMIDataUpdateCoordinator__update_best_weather_condition = lambda: None
    return coordinator


def test_optional_source_failure_preserves_current_weather_and_recovers():
    coordinator = _core_coordinator()
    weather = SimpleNamespace(
        data=SimpleNamespace(time=datetime.now(UTC)),
        place="Helsinki",
    )
    coordinator._fetch_forecast_weather = AsyncMock(return_value=weather)
    sea = object()
    lightning = [object()]

    def failed_lightning():
        raise ValueError("bad lightning XML")

    coordinator._FMIDataUpdateCoordinator__update_lightning_strikes = failed_lightning
    coordinator._FMIDataUpdateCoordinator__update_mareo_data = lambda: sea

    assert asyncio.run(coordinator._async_update_data()) == {"current": weather}
    assert coordinator.lightning_data is None
    assert coordinator.mareo_data is sea

    coordinator._FMIDataUpdateCoordinator__update_lightning_strikes = (
        lambda: lightning
    )

    def failed_sea():
        raise ValueError("bad sea-level XML")

    coordinator._FMIDataUpdateCoordinator__update_mareo_data = failed_sea
    assert asyncio.run(coordinator._async_update_data()) == {"current": weather}
    assert coordinator.lightning_data is lightning
    assert coordinator.mareo_data is None

    coordinator._FMIDataUpdateCoordinator__update_mareo_data = lambda: sea
    assert asyncio.run(coordinator._async_update_data()) == {"current": weather}
    assert coordinator.mareo_data is sea


def test_current_failure_does_not_execute_optional_sources():
    coordinator = _core_coordinator()
    old = SimpleNamespace(data=SimpleNamespace(time=datetime.now(UTC)))
    coordinator.current = old
    coordinator._fetch_forecast_weather = AsyncMock(
        return_value=SimpleNamespace(
            data=SimpleNamespace(time=datetime.now(UTC) - timedelta(days=1))
        )
    )
    extra = AsyncMock()
    coordinator._fetch_forecast = extra
    with pytest.raises(UpdateFailed, match="stale"):
        asyncio.run(coordinator._async_update_data())
    extra.assert_not_awaited()


def _observation_coordinator(api):
    Coordinator = source_definition(
        "__init__.py",
        "FMIObservationUpdateCoordinator",
        methods=["_fetch_observation", "_async_update_data"],
        base="object",
        namespace={
            "timeout": asyncio.timeout,
            "const": SimpleNamespace(
                TIMEOUT_FMI_INTEG_IN_SEC=2,
                OBSERVATION_MAX_AGE=timedelta(hours=2),
            ),
            "fmi": SimpleNamespace(async_observation_by_station_id=api),
            "fmi_erros": SimpleNamespace(ClientError=ClientError, ServerError=ServerError),
            "UpdateFailed": UpdateFailed,
            "is_fresh_weather": fresh_weather(),
            "timedelta": timedelta,
        },
    )
    coordinator = Coordinator()
    coordinator.logger = logging.getLogger("fmi.test.observation")
    coordinator.observation_station_id = 101
    coordinator.observation = None
    return coordinator


def test_station_outage_and_stale_data_do_not_republish_previous_readings():
    valid = SimpleNamespace(data=SimpleNamespace(time=datetime.now(UTC)))
    expired = SimpleNamespace(
        data=SimpleNamespace(time=datetime.now(UTC) - timedelta(days=1))
    )
    api = AsyncMock(side_effect=[valid, ServerError("down"), expired, valid])
    coordinator = _observation_coordinator(api)
    assert asyncio.run(coordinator._async_update_data()) == {"observation": valid}
    with pytest.raises(UpdateFailed):
        asyncio.run(coordinator._async_update_data())
    assert coordinator.observation is None
    with pytest.raises(UpdateFailed, match="stale"):
        asyncio.run(coordinator._async_update_data())
    assert coordinator.observation is None
    assert asyncio.run(coordinator._async_update_data()) == {"observation": valid}


def test_failed_station_initial_refresh_does_not_block_entry_setup():
    class MainCoordinator:
        last_update_success = True

        def __init__(self, *_args):
            pass

        async def async_config_entry_first_refresh(self):
            return None

    class StationCoordinator(MainCoordinator):
        async def async_config_entry_first_refresh(self):
            raise ConfigEntryNotReady("station unavailable")

    class Entry:
        entry_id = "abc"

        def add_update_listener(self, _callback):
            return lambda: None

    async def forward_entry_setups(_entry, _platforms):
        return None

    hass = SimpleNamespace(
        data={"fmi": {}},
        config_entries=SimpleNamespace(async_forward_entry_setups=forward_entry_setups),
    )
    const = SimpleNamespace(
        DOMAIN="fmi",
        COORDINATOR="coordinator",
        COORDINATOR_OBSERVATION="observation",
        UNDO_UPDATE_LISTENER="undo",
    )
    setup = source_definition(
        "__init__.py",
        "async_setup_entry",
        namespace={
            "async_get_clientsession": lambda _hass: object(),
            "FMIDataUpdateCoordinator": MainCoordinator,
            "FMIObservationUpdateCoordinator": StationCoordinator,
            "ConfigEntryNotReady": ConfigEntryNotReady,
            "update_listener": object(),
            "LOGGER": logging.getLogger("fmi.test.setup"),
            "const": const,
            "PLATFORMS": ["sensor", "weather"],
        },
    )
    assert asyncio.run(setup(hass, Entry()))
    assert isinstance(hass.data["fmi"]["abc"]["observation"], StationCoordinator)


class Entity:
    """Bare CoordinatorEntity replacement for availability checks."""

    def __init__(self):
        self.coordinator = None

    @property
    def available(self):
        return self.coordinator.last_update_success


def _sensor_property(class_name):
    return source_definition(
        "sensor.py",
        class_name,
        methods=["available"],
        base="Entity",
        namespace={
            "Entity": Entity,
            "SensorType": SimpleNamespace(PLACE=1, TIME=2),
        },
    )


def test_only_dependent_sensors_become_unavailable():
    c = SimpleNamespace(
        last_update_success=True,
        time_step=3,
        get_forecasts=list,
        lightning_data=None,
        mareo_data=None,
    )
    WeatherSensor = _sensor_property("FMIBestConditionSensor")
    best = WeatherSensor()
    best.coordinator = c
    best.type = 4
    assert not best.available
    best.type = 1
    assert best.available
    best.type = 2
    assert best.available

    lightning = _sensor_property("FMILightningStrikesSensor")()
    lightning.coordinator = c
    assert not lightning.available
    c.lightning_data = []
    assert lightning.available

    mareo = _sensor_property("FMIMareoSensor")()
    mareo.coordinator = c
    assert not mareo.available
    c.mareo_data = SimpleNamespace(size=lambda: 3)
    assert mareo.available

    c.last_update_success = False
    assert not best.available
    assert not lightning.available
    assert not mareo.available
