"""Regression tests for SensorEntity migration without requiring Home Assistant."""

import ast
import enum
import logging
import math
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from conftest import SOURCE_ROOT, source_definition


class FakeCoordinatorEntity:
    """Minimal managed coordinator state and availability."""

    def __init__(self, coordinator):
        self.coordinator = coordinator

    @property
    def available(self):
        return self.coordinator.last_update_success

    def _handle_coordinator_update(self):
        self.writes = getattr(self, "writes", 0) + 1


def _metadata():
    """Evaluate only static descriptions from production source definitions."""
    SensorType = source_definition(
        "sensor.py", "SensorType", namespace={"enum": enum}
    )
    device_classes = SimpleNamespace(
        TEMPERATURE="temperature",
        WIND_SPEED="wind_speed",
        HUMIDITY="humidity",
        PRECIPITATION_INTENSITY="precipitation_intensity",
        DISTANCE="distance",
    )
    units = SimpleNamespace(
        UnitOfTemperature=SimpleNamespace(CELSIUS="°C"),
        UnitOfSpeed=SimpleNamespace(METERS_PER_SECOND="m/s"),
        UnitOfVolumetricFlux=SimpleNamespace(MILLIMETERS_PER_HOUR="mm/h"),
        UnitOfLength=SimpleNamespace(CENTIMETERS="cm"),
        PERCENTAGE="%",
    )
    scope = {
        "SensorType": SensorType,
        "SensorEntityDescription": lambda **kwargs: SimpleNamespace(**kwargs),
        "SensorDeviceClass": device_classes,
        "ha_const": units,
    }
    wanted = {
        "SENSOR_TYPES",
        "SENSOR_LIGHTNING_TYPES",
        "SENSOR_MAREO_TYPES",
        "_SENSOR_DEVICE_CLASSES",
        "_CURRENT_MEASUREMENTS",
        "SENSOR_DESCRIPTIONS",
    }
    tree = ast.parse((SOURCE_ROOT / "sensor.py").read_text(encoding="utf-8"))
    statements = [
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id in wanted
            for target in node.targets
        )
    ]
    module = ast.fix_missing_locations(ast.Module(body=statements, type_ignores=[]))
    # The checked-out repository is the only source executed here.
    exec(compile(module, str(SOURCE_ROOT / "sensor.py"), "exec"), scope)  # noqa: S102
    return scope


def _weather(temperature=5, wind=4, wind_direction=180):
    fields = {
        "temperature": temperature,
        "wind_speed": wind,
        "wind_gust": 7,
        "wind_direction": wind_direction,
        "humidity": 64,
        "cloud_cover": 20,
        "precipitation_amount": 0,
    }
    data = SimpleNamespace(
        time=datetime(2026, 10, 22, 10, 30, tzinfo=UTC),
        symbol=SimpleNamespace(value=2),
        **{key: SimpleNamespace(value=value) if value is not None else None
           for key, value in fields.items()},
    )
    return SimpleNamespace(place="Helsinki", data=data)


class FakeCoordinator:
    unique_id = "60.17:24.94"
    last_update_success = True
    time_step = 1
    best_time = datetime(2026, 10, 22, 12, tzinfo=UTC)
    best_temperature = 10
    best_humidity = 50
    best_precipitation = 0
    best_wind_speed = 2

    def __init__(self, weather=None, forecasts=None, timestep=1):
        self.current = weather if weather is not None else _weather()
        self.forecasts = forecasts if forecasts is not None else []
        self.time_step = timestep
        self.lightning_data = None
        self.mareo_data = None

    def get_weather(self):
        return self.current

    def get_current_place(self):
        return self.current.place if self.current else None

    def get_forecasts(self):
        return self.forecasts


def _classes():
    scope = _metadata()
    scope.update({
        "CoordinatorEntity": FakeCoordinatorEntity,
        "FMIDataUpdateCoordinator": FakeCoordinator,
        "SensorStateClass": SimpleNamespace(MEASUREMENT="measurement"),
        "ha_core": SimpleNamespace(callback=lambda fn: fn),
        "const": SimpleNamespace(
            LOGGER=logging.getLogger("test.sensor"),
            ATTRIBUTION="Weather Data provided by FMI",
            ATTR_HUMIDITY="relative_humidity",
            ATTR_PRECIPITATION="precipitation",
            ATTR_WIND_SPEED="wind_speed",
            ATTR_DISTANCE="distance",
            ATTR_STRIKES="strikes",
            ATTR_PEAK_CURRENT="peak_current",
            ATTR_CLOUD_COVER="cloud_cover",
            ATTR_ELLIPSE_MAJOR="ellipse_major",
        ),
        "ha_const": SimpleNamespace(
            ATTR_LOCATION="location",
            ATTR_TIME="time",
            ATTR_TEMPERATURE="temperature",
            ATTR_ATTRIBUTION="attribution",
        ),
        "tz": SimpleNamespace(tzlocal=lambda: UTC),
        "datetime": datetime,
        "math": math,
        "utils": SimpleNamespace(
            get_weather_symbol=lambda symbol: {1: "sunny", 2: "partlycloudy"}
            .get(symbol, "")
        ),
    })
    Base = source_definition(
        "sensor.py", "_BaseSensorClass", base="CoordinatorEntity",
        namespace=scope,
    )
    scope["Base"] = Base
    types = {
        name: source_definition(
            "sensor.py", name, base="Base", namespace=scope
        )
        for name in (
            "FMIBestConditionSensor",
            "FMILightningStrikesSensor",
            "FMIMareoSensor",
        )
    }
    return scope, types


def _sensor(kind, coordinator=None):
    scope, classes = _classes()
    SensorType = scope["SensorType"]
    c = coordinator if coordinator is not None else FakeCoordinator()
    if kind == SensorType.LIGHTNING:
        cls = classes["FMILightningStrikesSensor"]
        spec = scope["SENSOR_LIGHTNING_TYPES"][kind]
    elif kind == SensorType.SEA_LEVEL:
        cls = classes["FMIMareoSensor"]
        spec = scope["SENSOR_MAREO_TYPES"][kind]
    else:
        cls = classes["FMIBestConditionSensor"]
        spec = scope["SENSOR_TYPES"][kind]
    return cls("Home", c, kind, spec)


def test_sensor_platform_uses_real_sensor_entity_inheritance_and_native_attrs():
    tree = ast.parse((SOURCE_ROOT / "sensor.py").read_text(encoding="utf-8"))
    base = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "_BaseSensorClass"
    )
    assert [node.id for node in base.bases] == ["CoordinatorEntity", "SensorEntity"]
    legacy_writes = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.ctx, ast.Store)
        and node.attr in ("_attr_state", "_attr_unit_of_measurement")
    ]
    assert legacy_writes == []


def test_descriptions_cover_every_published_sensor_with_stable_units():
    scope = _metadata()
    SensorType = scope["SensorType"]
    descriptions = scope["SENSOR_DESCRIPTIONS"]
    sensor_defs = (
        scope["SENSOR_TYPES"]
        | scope["SENSOR_LIGHTNING_TYPES"]
        | scope["SENSOR_MAREO_TYPES"]
    )
    assert set(descriptions) == set(sensor_defs)
    assert len(descriptions) == 13
    for kind, legacy in sensor_defs.items():
        description = descriptions[kind]
        assert description.name == legacy[0]
        assert description.icon == legacy[2]
        assert description.native_unit_of_measurement == (legacy[1] or None)
    assert descriptions[SensorType.TEMPERATURE].device_class == "temperature"
    assert descriptions[SensorType.WIND_SPEED].device_class == "wind_speed"
    assert descriptions[SensorType.RAIN].device_class == "precipitation_intensity"
    assert descriptions[SensorType.RAIN].native_unit_of_measurement == "mm/h"
    assert descriptions[SensorType.SEA_LEVEL].device_class == "distance"
    assert descriptions[SensorType.SEA_LEVEL].native_unit_of_measurement == "cm"
    assert descriptions[SensorType.WIND_DIR].device_class is None


@pytest.mark.parametrize("kind", list(range(1, 14)))
def test_all_legacy_sensor_id_and_name_contracts(kind):
    scope = _metadata()
    SensorType = scope["SensorType"]
    sensor_type = SensorType(kind)
    entity = _sensor(sensor_type)
    description = scope["SENSOR_DESCRIPTIONS"][sensor_type]
    expected_id = f"60.17:24.94_Home_{description.name.replace(' ', '_')}"
    assert entity._attr_unique_id == expected_id
    if sensor_type in (SensorType.LIGHTNING, SensorType.SEA_LEVEL):
        assert entity._attr_name == "Helsinki " + description.name
    else:
        assert entity._attr_name == description.name
    assert entity._attr_should_poll is False
    assert entity._attr_native_unit_of_measurement == (
        description.native_unit_of_measurement
    )
    assert not hasattr(entity, "_attr_state")
    assert not hasattr(entity, "_attr_unit_of_measurement")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (0, 0),
        (-7.5, -7.5),
        (None, None),
        (float("nan"), None),
        (float("inf"), None),
        (-float("inf"), None),
        ("5", None),
        (True, None),
    ],
)
def test_native_numeric_value_rejects_invalid_numbers(value, expected):
    scope = _metadata()
    weather = _weather(temperature=value)
    entity = _sensor(scope["SensorType"].TEMPERATURE, FakeCoordinator(weather))
    assert entity._attr_native_value == expected
    assert entity._attr_native_unit_of_measurement == "°C"


def test_missing_numeric_field_is_unknown_not_the_string_unavailable():
    kind = _metadata()["SensorType"].WIND_GUST
    weather = _weather()
    del weather.data.wind_gust
    entity = _sensor(kind, FakeCoordinator(weather))
    assert entity._attr_native_value is None
    assert entity.available


@pytest.mark.parametrize(
    ("degrees", "expected"),
    [(0, "N"), (45, "NE"), (90, "E"), (180, "S"),
     (270, "W"), (315, "NW"), (360, "N"),
     (None, None), (float("nan"), None), (400, None)],
)
def test_wind_direction_remains_text(degrees, expected):
    scope = _metadata()
    kind = scope["SensorType"].WIND_DIR
    entity = _sensor(kind, FakeCoordinator(_weather(wind_direction=degrees)))
    assert entity._attr_native_value == expected
    assert entity._attr_native_unit_of_measurement is None
    assert entity._attr_state_class is None


def test_forecast_sensor_not_misclassified_as_historical_measurement():
    scope = _metadata()
    SensorType = scope["SensorType"]
    forecast = SimpleNamespace(
        time=datetime(2026, 10, 22, 14, tzinfo=UTC),
        temperature=SimpleNamespace(value=-4),
    )
    c = FakeCoordinator(timestep=3, forecasts=[forecast])
    entity = _sensor(SensorType.TEMPERATURE, c)
    assert entity._attr_native_value == -4
    assert entity._attr_state_class is None
    assert entity.available
    c.forecasts = []
    entity.update_callback()
    assert entity._attr_native_value is None
    assert not entity.available


def test_current_measurements_can_record_statistics_but_text_cannot():
    scope = _metadata()
    SensorType = scope["SensorType"]
    for kind in scope["_CURRENT_MEASUREMENTS"]:
        entity = _sensor(kind)
        assert entity._attr_state_class == "measurement"
    for kind in (SensorType.PLACE, SensorType.WEATHER, SensorType.WIND_DIR,
                 SensorType.TIME, SensorType.TIME_FORECAST,
                 SensorType.LIGHTNING, SensorType.SEA_LEVEL):
        entity = _sensor(kind)
        assert entity._attr_state_class is None


def test_place_condition_and_best_time_keep_string_values():
    scope = _metadata()
    SensorType = scope["SensorType"]
    assert _sensor(SensorType.PLACE)._attr_native_value == "Helsinki"
    assert _sensor(SensorType.WEATHER)._attr_native_value == "partlycloudy"
    assert _sensor(SensorType.TIME)._attr_native_value == "12:00"
    assert _sensor(SensorType.TIME_FORECAST)._attr_native_value == "10:30"


def test_missing_weather_clears_last_value_and_extra_attributes():
    scope = _metadata()
    SensorType = scope["SensorType"]
    coordinator = FakeCoordinator()
    entity = _sensor(SensorType.TEMPERATURE, coordinator)
    assert entity._attr_native_value == 5
    assert entity._attr_extra_state_attributes["location"] == "Helsinki"
    coordinator.current = None
    entity.update_callback()
    assert entity._attr_native_value is None
    assert entity._attr_extra_state_attributes == {}


def test_source_failure_and_empty_strikes_remain_distinct():
    scope = _metadata()
    coordinator = FakeCoordinator()
    lightning = _sensor(scope["SensorType"].LIGHTNING, coordinator)
    assert not lightning.available
    assert lightning._attr_native_value is None
    coordinator.lightning_data = []
    lightning.update()
    assert lightning.available
    assert lightning._attr_native_value is None
    coordinator.lightning_data = [
        SimpleNamespace(
            location="Helsinki", time="12:00", distance=5,
            strikes=1, peak_current=4, cloud_cover=30, ellipse_major=2,
        )
    ]
    lightning.update()
    assert lightning._attr_native_value == "Helsinki"
    assert lightning._attr_extra_state_attributes["strikes"] == 1
    coordinator.lightning_data = None
    lightning.update()
    assert lightning._attr_extra_state_attributes == {}
    assert not lightning.available


def test_sea_level_native_cm_preserves_forecasts_attribute():
    scope = _metadata()
    coordinator = FakeCoordinator()
    entry = SimpleNamespace(time="12:00", sea_level=32.5)
    next_entry = SimpleNamespace(time="12:30", sea_level=35.0)
    coordinator.mareo_data = SimpleNamespace(
        size=lambda: 2,
        get_values=lambda: [entry, next_entry],
    )
    entity = _sensor(scope["SensorType"].SEA_LEVEL, coordinator)
    assert entity._attr_native_value == 32.5
    assert entity._attr_native_unit_of_measurement == "cm"
    assert entity._attr_extra_state_attributes["FORECASTS"] == [
        {"time": "12:30", "height": 35.0}
    ]
    coordinator.mareo_data = None
    entity.update()
    assert entity._attr_native_value is None
    assert entity._attr_extra_state_attributes == {}
    assert not entity.available


def test_coordinator_updates_recompute_native_value_then_write_once():
    kind = _metadata()["SensorType"].TEMPERATURE
    coordinator = FakeCoordinator()
    entity = _sensor(kind, coordinator)
    coordinator.current.data.temperature.value = 9
    entity._handle_coordinator_update()
    assert entity._attr_native_value == 9
    assert entity.writes == 1
