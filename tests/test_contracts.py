"""Public identity contracts: these must not change unintentionally in PR2+."""

import ast
import logging
from types import SimpleNamespace

import pytest
from conftest import ROOT, source_definition


class DummyCoordinatorEntity:
    """The only CoordinatorEntity behavior needed by constructors."""

    def __init__(self, coordinator):
        self.coordinator = coordinator


class FakeCoordinator:
    unique_id = "60.17:24.94"
    last_update_success = False

    def get_weather(self):
        return None

    def get_observation(self):
        return None

    def get_current_place(self):
        return "Helsinki"

    def async_add_listener(self, callback):
        return lambda: None


def _legacy_constants():
    """Read public string keys without importing Home Assistant."""
    tree = ast.parse((ROOT / "const.py").read_text(encoding="utf-8"))
    values = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    try:
                        values[target.id] = ast.literal_eval(node.value)
                    except (ValueError, TypeError, SyntaxError, MemoryError):
                        pass
    return values


def test_config_entry_unique_id_uses_original_format():
    base_unique_id = source_definition("__init__.py", "base_unique_id")
    assert base_unique_id(60.17, 24.94) == "60.17_24.94"
    assert base_unique_id(0, -1.0) == "0_-1.0"


def test_persisted_config_option_keys():
    constants = _legacy_constants()
    assert constants["DOMAIN"] == "fmi"
    assert {
        key: constants[key]
        for key in (
            "CONF_FORECAST_DAYS",
            "CONF_DAILY_MODE",
            "CONF_LIGHTNING",
            "CONF_LIGHTNING_DISTANCE",
            "CONF_OBSERVATION_STATION",
            "CONF_MIN_TEMP",
            "CONF_MAX_TEMP",
        )
    } == {
        "CONF_FORECAST_DAYS": "forecast_days",
        "CONF_DAILY_MODE": "daily_mode",
        "CONF_LIGHTNING": "lightning_sensor",
        "CONF_LIGHTNING_DISTANCE": "lightning_radius",
        "CONF_OBSERVATION_STATION": "observation_station_id",
        "CONF_MIN_TEMP": "min_temperature",
        "CONF_MAX_TEMP": "max_temperature",
    }


@pytest.mark.parametrize(
    ("daily_mode", "station_id", "coordinator_id", "expected_id", "expected_name"),
    [
        (False, False, "60.17:24.94", "60.17:24.94", "Home"),
        (True, False, "60.17:24.94", "60.17:24.94_daily", "Home (daily)"),
        (
            False,
            True,
            "60.17:24.94_observation",
            "60.17:24.94_observation_observation",
            "Home (observation)",
        ),
    ],
)
def test_weather_entity_identity(
    daily_mode, station_id, coordinator_id, expected_id, expected_name
):
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
        methods=["__init__"],
        base="CoordinatorEntity",
        namespace={
            "CoordinatorEntity": DummyCoordinatorEntity,
            "const": const,
            "DeviceEntryType": SimpleNamespace(SERVICE="service"),
        },
    )
    Weather.update_callback = lambda self: None
    coordinator = FakeCoordinator()
    coordinator.unique_id = coordinator_id
    entity = Weather("Home", coordinator, station_id=station_id, daily_mode=daily_mode)
    assert entity._attr_unique_id == expected_id
    assert entity._attr_name == expected_name
    assert entity._attr_should_poll is False


@pytest.mark.parametrize(
    ("display_name", "expected_id"),
    [
        ("Temperature", "60.17:24.94_My_Home_Temperature"),
        ("Wind Speed", "60.17:24.94_My_Home_Wind_Speed"),
        ("Best Time Of Day", "60.17:24.94_My_Home_Best_Time_Of_Day"),
    ],
)
def test_sensor_entity_identity(display_name, expected_id):
    Base = source_definition(
        "sensor.py",
        "_BaseSensorClass",
        methods=["__init__"],
        base="CoordinatorEntity",
        namespace={
            "CoordinatorEntity": DummyCoordinatorEntity,
            "const": SimpleNamespace(
                LOGGER=logging.getLogger("test.fmi"),
                ATTRIBUTION="Weather Data provided by FMI",
            ),
            "ha_const": SimpleNamespace(STATE_UNAVAILABLE="unavailable"),
        },
    )
    Base.update = lambda self: None
    Base.update_callback = lambda self: None
    entity = Base(
        "My Home",
        FakeCoordinator(),
        1,
        [display_name, None, "mdi:test"],
        only_name=True,
    )
    assert entity._attr_unique_id == expected_id
    assert entity._attr_name == display_name
    assert entity._attr_should_poll is False
