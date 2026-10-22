"""Support for weather service from FMI (Finnish Meteorological Institute) for sensor platform."""

import enum
import math
from datetime import datetime
from dateutil import tz
# Import homeassistant platform dependencies
import homeassistant.const as ha_const
import homeassistant.core as ha_core
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import FMIDataUpdateCoordinator
from . import utils
from . import const


class SensorType(enum.IntEnum):
    PLACE = enum.auto()
    WEATHER = enum.auto()
    TEMPERATURE = enum.auto()
    WIND_SPEED = enum.auto()
    WIND_DIR = enum.auto()
    WIND_GUST = enum.auto()
    HUMIDITY = enum.auto()
    CLOUDS = enum.auto()
    RAIN = enum.auto()
    TIME_FORECAST = enum.auto()
    TIME = enum.auto()
    LIGHTNING = enum.auto()
    SEA_LEVEL = enum.auto()


SENSOR_TYPES = {
    SensorType.PLACE: ["Place", None, "mdi:city-variant"],
    SensorType.WEATHER: ["Condition", None, None],
    SensorType.TEMPERATURE: ["Temperature", ha_const.UnitOfTemperature.CELSIUS,
                             "mdi:thermometer"],
    SensorType.WIND_SPEED: ["Wind Speed", ha_const.UnitOfSpeed.METERS_PER_SECOND,
                            "mdi:weather-windy"],
    SensorType.WIND_DIR: ["Wind Direction", "", "mdi:weather-windy"],
    SensorType.WIND_GUST: ["Wind Gust", ha_const.UnitOfSpeed.METERS_PER_SECOND,
                           "mdi:weather-windy"],
    SensorType.HUMIDITY: ["Humidity", ha_const.PERCENTAGE, "mdi:water"],
    SensorType.CLOUDS: ["Cloud Coverage", ha_const.PERCENTAGE, "mdi:weather-cloudy"],
    SensorType.RAIN: ["Rain", ha_const.UnitOfVolumetricFlux.MILLIMETERS_PER_HOUR,
                      "mdi:weather-pouring"],
    SensorType.TIME_FORECAST: ["Time", None, "mdi:av-timer"],
    SensorType.TIME: ["Best Time Of Day", None, "mdi:av-timer"],
}

SENSOR_LIGHTNING_TYPES = {
    SensorType.LIGHTNING: ["Lightning Strikes", None, "mdi:weather-lightning"]
}

SENSOR_MAREO_TYPES = {
    SensorType.SEA_LEVEL: ["Sea Level", ha_const.UnitOfLength.CENTIMETERS, "mdi:waves"]
}

# Preserve the existing sensor names, IDs and icons while declaring native
# HA types/units in one place. No translation key or has_entity_name migration.
_SENSOR_DEVICE_CLASSES = {
    SensorType.TEMPERATURE: SensorDeviceClass.TEMPERATURE,
    SensorType.WIND_SPEED: SensorDeviceClass.WIND_SPEED,
    SensorType.WIND_GUST: SensorDeviceClass.WIND_SPEED,
    SensorType.HUMIDITY: SensorDeviceClass.HUMIDITY,
    SensorType.RAIN: SensorDeviceClass.PRECIPITATION_INTENSITY,
    SensorType.SEA_LEVEL: SensorDeviceClass.DISTANCE,
}

_CURRENT_MEASUREMENTS = frozenset((
    SensorType.TEMPERATURE,
    SensorType.WIND_SPEED,
    SensorType.WIND_GUST,
    SensorType.HUMIDITY,
    SensorType.CLOUDS,
    SensorType.RAIN,
))

SENSOR_DESCRIPTIONS = {
    sensor_type: SensorEntityDescription(
        key=sensor_type.name.lower(),
        name=sensor_data[0],
        icon=sensor_data[2],
        native_unit_of_measurement=sensor_data[1] or None,
        device_class=_SENSOR_DEVICE_CLASSES.get(sensor_type),
    )
    for sensor_type, sensor_data in (
        SENSOR_TYPES | SENSOR_LIGHTNING_TYPES | SENSOR_MAREO_TYPES
    ).items()
}

PARALLEL_UPDATES = 1


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the FMI Sensor, including Best Time Of the Day sensor."""
    name = config_entry.data[ha_const.CONF_NAME]
    lightning_mode = config_entry.options.get(const.CONF_LIGHTNING, False)

    coordinator = hass.data[const.DOMAIN][config_entry.entry_id][const.COORDINATOR]

    entity_list = []

    for sensor_type, sensor_data in SENSOR_TYPES.items():
        entity_list.append(
            FMIBestConditionSensor(
                name, coordinator, sensor_type, sensor_data))

    if lightning_mode:
        for sensor_type, sensor_data in SENSOR_LIGHTNING_TYPES.items():
            entity_list.append(
                FMILightningStrikesSensor(name, coordinator, sensor_type, sensor_data))

    for sensor_type, sensor_data in SENSOR_MAREO_TYPES.items():
        entity_list.append(
            FMIMareoSensor(name, coordinator, sensor_type, sensor_data))

    async_add_entities(entity_list, False)


class _BaseSensorClass(CoordinatorEntity, SensorEntity):
    """Common base class for all the sensor types."""

    def __init__(self, name, coordinator: FMIDataUpdateCoordinator,
                 sensor_type, sensor_data, only_name=None):
        """Initialize the sensor base data."""
        self.logger = const.LOGGER.getChild("sensor")
        super().__init__(coordinator)
        self.client_name = name
        self._name, unit, self._attr_icon = sensor_data
        self.type = sensor_type
        self.entity_description = SENSOR_DESCRIPTIONS.get(sensor_type)
        self._attr_native_unit_of_measurement = unit or None
        self._attr_native_value = None
        self._attr_extra_state_attributes = {}
        # Forecasts are predictions rather than current measurements, and
        # should not generate misleading long-term statistics in HA.
        self._attr_state_class = (
            SensorStateClass.MEASUREMENT
            if sensor_type in _CURRENT_MEASUREMENTS and coordinator.time_step == 1
            else None
        )
        self._attr_unique_id = \
            f"{coordinator.unique_id}_{name.replace(' ', '_')}_{self._name.replace(' ', '_')}"
        if only_name:
            self._attr_name = f"{self._name}"
        else:
            base_name = coordinator.get_current_place()
            if base_name is None:
                base_name = name
            self._attr_name = f"{base_name} {self._name}"
        self._attr_attribution = const.ATTRIBUTION
        self._attr_should_poll = False
        self.update()

    @ha_core.callback
    def _handle_coordinator_update(self) -> None:
        """Refresh sensor attributes before the coordinator publishes state."""
        self.update_callback()
        super()._handle_coordinator_update()

    def update_callback(self, *_, **__):
        """Update the entity attributes."""
        _fmi: FMIDataUpdateCoordinator = self.coordinator
        _weather = _fmi.get_weather()
        if not _weather:
            self._attr_native_value = None
            self._attr_extra_state_attributes = {}
            return
        _time = _weather.data.time.astimezone(tz.tzlocal())
        self.logger.debug(
            "%s: updated: %s time %s",
            self._attr_name, _fmi.last_update_success, _time,
        )
        self.update()

    def update(self):
        """Update method prototype."""
        raise NotImplementedError("Required update method is not implemented")


class FMIBestConditionSensor(_BaseSensorClass):
    """Implementation of a FMI Weather sensor with best conditions of the day."""

    @property
    def available(self):
        """A missing optional forecast must not expose old forecast sensor values."""
        if not super().available:
            return False
        if self.type == SensorType.PLACE:
            return True
        if self.type == SensorType.TIME:
            return self.coordinator.best_time is not None
        return (self.coordinator.time_step == 1
                or bool(self.coordinator.get_forecasts()))

    def __init__(self, name, coordinator, sensor_type, sensor_data):
        """Initialize the sensor."""
        self.update_state_func = {
            SensorType.WEATHER: self.__update_weather,
            SensorType.TEMPERATURE: self.__update_temperature,
            SensorType.WIND_SPEED: self.__update_wind_speed,
            SensorType.WIND_DIR: self.__update_wind_direction,
            SensorType.WIND_GUST: self.__update_wind_gust,
            SensorType.HUMIDITY: self.__update_humidity,
            SensorType.CLOUDS: self.__update_clouds,
            SensorType.RAIN: self.__update_rain,
            SensorType.TIME_FORECAST: self.__update_forecast_time,
            SensorType.TIME: self.__update_time,
        }.get(sensor_type, self.__update_dummy)
        super().__init__(name, coordinator, sensor_type, sensor_data, only_name=True)

    @staticmethod
    def get_wind_direction_string(wind_direction_in_deg):
        """Get the string interpretation of wind direction in degrees."""

        if (wind_direction_in_deg is None
                or not math.isfinite(wind_direction_in_deg)
                or wind_direction_in_deg < 0 or wind_direction_in_deg > 360):
            return None

        if wind_direction_in_deg <= 23 or wind_direction_in_deg > 338:
            return "N"
        if 23 < wind_direction_in_deg <= 68:
            return "NE"
        if 68 < wind_direction_in_deg <= 113:
            return "E"
        if 113 < wind_direction_in_deg <= 158:
            return "SE"
        if 158 < wind_direction_in_deg <= 203:
            return "S"
        if 203 < wind_direction_in_deg <= 248:
            return "SW"
        if 248 < wind_direction_in_deg <= 293:
            return "W"
        if 293 < wind_direction_in_deg <= 338:
            return "NW"
        return None

    @staticmethod
    def _finite_value(source_data, name):
        """Return a finite FMI numeric value, including zero, or None."""
        wrapped = getattr(source_data, name, None)
        value = getattr(wrapped, "value", None)
        if (isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)):
            return value
        return None

    def __convert_float(self, source_data, name):
        self._attr_native_value = self._finite_value(source_data, name)

    def __update_dummy(self, source_data):
        _ = source_data
        self._attr_native_value = None

    def __update_forecast_time(self, source_data):
        forecast_time = getattr(source_data, "time", None)
        self._attr_native_value = (
            forecast_time.astimezone(tz.tzlocal()).strftime("%H:%M")
            if forecast_time is not None else None
        )

    def __update_weather(self, source_data):
        symbol = getattr(getattr(source_data, "symbol", None), "value", None)
        self._attr_native_value = (
            utils.get_weather_symbol(symbol) or None
            if symbol is not None else None
        )

    def __update_temperature(self, source_data):
        self.__convert_float(source_data, "temperature")

    def __update_wind_speed(self, source_data):
        self.__convert_float(source_data, "wind_speed")

    def __update_wind_direction(self, source_data):
        bearing = self._finite_value(source_data, "wind_direction")
        self._attr_native_value = self.get_wind_direction_string(bearing)

    def __update_wind_gust(self, source_data):
        self.__convert_float(source_data, "wind_gust")

    def __update_humidity(self, source_data):
        self.__convert_float(source_data, "humidity")

    def __update_clouds(self, source_data):
        self.__convert_float(source_data, "cloud_cover")

    def __update_rain(self, source_data):
        self.__convert_float(source_data, "precipitation_amount")

    def __update_time(self, source_data):
        _ = source_data
        _fmi: FMIDataUpdateCoordinator = self.coordinator
        self._attr_native_value = (
            _fmi.best_time.strftime("%H:%M")
            if _fmi.best_time is not None else None
        )

    def update(self):
        """Update the state of the weather sensor."""

        self.logger.debug("FMI: Sensor %s is updating", self._attr_name)

        _fmi: FMIDataUpdateCoordinator = self.coordinator
        weather = _fmi.get_weather()

        if weather is None:
            self._attr_native_value = None
            self._attr_extra_state_attributes = {}
            return

        # update the extra state attributes
        self._attr_extra_state_attributes = {
            ha_const.ATTR_LOCATION: weather.place,
            ha_const.ATTR_TIME: _fmi.best_time,
            ha_const.ATTR_TEMPERATURE: _fmi.best_temperature,
            const.ATTR_HUMIDITY: _fmi.best_humidity,
            const.ATTR_PRECIPITATION: _fmi.best_precipitation,
            const.ATTR_WIND_SPEED: _fmi.best_wind_speed,
            ha_const.ATTR_ATTRIBUTION: const.ATTRIBUTION,
        }

        if self.type == SensorType.PLACE:
            self._attr_native_value = weather.place
            return

        self._attr_native_value = None
        source_data = None

        # Update the sensor states
        if _fmi.time_step == 1 or self.type == SensorType.TIME:
            # The place and best-time values use the current weather snapshot.
            source_data = weather.data
        else:
            # Forecasted weather based on configured time_step - next forecasted hour, if available

            _forecasts = _fmi.get_forecasts()

            if not _forecasts:
                self.logger.debug("FMI: Sensor _FMI Hourly Forecast is unavailable")
                return

            # If current time is half past or more then use the hour next to next hour
            # otherwise fallback to the next hour
            if len(_forecasts) > 1:
                curr_min = datetime.now().minute
                source_data = _forecasts[1 if curr_min >= 30 else 0]
            else:
                source_data = _forecasts[0]

        if source_data is None:
            self.logger.debug("FMI: Sensor Source data is unavailable")
            return

        self.update_state_func(source_data)


class FMILightningStrikesSensor(_BaseSensorClass):
    """Implementation of a FMI Lightning strikes sensor."""

    @property
    def available(self):
        """No strikes is a valid result; a failed query is not."""
        return (super().available
                and self.coordinator.lightning_data is not None)

    def update(self):
        """Update the state of the lightning sensor."""

        self.logger.debug("FMI: update lightning sensor %s", self._attr_name)

        _fmi: FMIDataUpdateCoordinator = self.coordinator
        _data = _fmi.lightning_data

        if not _data:
            # No strikes is valid if the source responded successfully;
            # failed queries are distinguished by the available property.
            self._attr_native_value = None
            self._attr_extra_state_attributes = {}
            return

        self._attr_native_value = _data[0].location

        # update the extra state attributes
        self._attr_extra_state_attributes = {
            ha_const.ATTR_LOCATION: _data[0].location,
            ha_const.ATTR_TIME: _data[0].time,
            const.ATTR_DISTANCE: _data[0].distance,
            const.ATTR_STRIKES: _data[0].strikes,
            const.ATTR_PEAK_CURRENT: _data[0].peak_current,
            const.ATTR_CLOUD_COVER: _data[0].cloud_cover,
            const.ATTR_ELLIPSE_MAJOR: _data[0].ellipse_major,
            "OBSERVATIONS": [
                {
                    ha_const.ATTR_LOCATION: strike.location,
                    ha_const.ATTR_TIME: strike.time,
                    const.ATTR_DISTANCE: strike.distance,
                    const.ATTR_STRIKES: strike.strikes,
                    const.ATTR_PEAK_CURRENT: strike.peak_current,
                    const.ATTR_CLOUD_COVER: strike.cloud_cover,
                    const.ATTR_ELLIPSE_MAJOR: strike.ellipse_major,
                }
                for strike in _data[1:]
            ],
            ha_const.ATTR_ATTRIBUTION: const.ATTRIBUTION,
        }


class FMIMareoSensor(_BaseSensorClass):
    """Implementation of a FMI sea water level sensor."""

    @property
    def available(self):
        """Sea-level failures never expose the last successful sea-level value."""
        mareo = self.coordinator.mareo_data
        return (super().available
                and mareo is not None and bool(mareo.size()))

    def update(self):
        """Update the state of the mareo sensor."""

        self.logger.debug("FMI: update mareo sensor %s", self._attr_name)

        _fmi: FMIDataUpdateCoordinator = self.coordinator
        mareo = _fmi.mareo_data

        if not mareo or not mareo.size():
            self._attr_native_value = None
            self._attr_extra_state_attributes = {}
            self.logger.debug("FMI: Sensor mareo is unavailable")
            return

        mareo_data = mareo.get_values()

        self._attr_native_value = mareo_data[0].sea_level

        # update the extra state attributes
        self._attr_extra_state_attributes = {
            ha_const.ATTR_TIME: mareo_data[0].time,
            "FORECASTS": [
                {"time": item.time, "height": item.sea_level} for item in mareo_data[1:]
            ],
            ha_const.ATTR_ATTRIBUTION: const.ATTRIBUTION,
        }
