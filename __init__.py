"""The FMI (Finnish Meteorological Institute) component."""

import typing
import time
from datetime import datetime, timedelta, timezone

import fmi_weather_client as fmi
import fmi_weather_client.models as fmi_models
import fmi_weather_client.errors as fmi_erros
import requests
from async_timeout import timeout
from dateutil import tz
from geopy.geocoders import Nominatim
from homeassistant.util import dt as dt_util
from homeassistant.const import CONF_LATITUDE, CONF_LONGITUDE, CONF_OFFSET
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import (DataUpdateCoordinator,
                                                      UpdateFailed)

from . import utils
from . import const
from .wfs import (
    CachedReverseGeocoder,
    local_display_time,
    parse_lightning,
    parse_sea_level,
    utc_time_parameter,
)


LOGGER = const.LOGGER
PLATFORMS = ["sensor", "weather"]


def base_unique_id(latitude, longitude):
    """Return unique id for entries in configuration."""
    return f"{latitude}_{longitude}"


def is_fresh_weather(weather, max_age, max_future=timedelta(hours=2), now=None):
    """Reject missing, naive or outdated FMI measurements.

    FMI supplies timezone-aware timestamps. Future forecast estimates are
    allowed a small tolerance, but old responses are not reported as fresh.
    """
    timestamp = getattr(getattr(weather, "data", None), "time", None)
    if not isinstance(timestamp, datetime) or timestamp.tzinfo is None:
        return False
    if timestamp.utcoffset() is None:
        return False
    if now is None:
        now = datetime.now(timezone.utc)
    age = now - timestamp.astimezone(timezone.utc)
    return -max_future <= age <= max_age


def has_future_forecast(forecast, now=None):
    """Check for at least one valid future forecast slot."""
    if now is None:
        now = datetime.now(timezone.utc)
    for point in getattr(forecast, "forecasts", ()) or ():
        timestamp = getattr(point, "time", None)
        if (isinstance(timestamp, datetime)
                and timestamp.tzinfo is not None
                and timestamp.utcoffset() is not None
                and timestamp.astimezone(timezone.utc) > now):
            return True
    return False


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up configured FMI."""
    _ = config
    hass.data.setdefault(const.DOMAIN, {})
    return True


async def async_setup_entry(hass, config_entry) -> bool:
    """Set up FMI as config entry."""
    websession = async_get_clientsession(hass)

    coordinator = FMIDataUpdateCoordinator(
        hass, websession, config_entry
    )
    await coordinator.async_config_entry_first_refresh()

    if not coordinator.last_update_success:
        raise ConfigEntryNotReady

    try:
        coordinator_observation = FMIObservationUpdateCoordinator(
            hass, websession, config_entry)
    except AttributeError:
        # A station is not configured; only the forecast coordinator is needed.
        coordinator_observation = None
    if coordinator_observation is not None:
        try:
            await coordinator_observation.async_config_entry_first_refresh()
        except ConfigEntryNotReady:
            # Keep the station coordinator registered. Its entity is unavailable
            # until the next successful station poll, without blocking setup.
            LOGGER.warning(
                "FMI observation station is unavailable; continuing with forecast"
            )

    undo_listener = config_entry.add_update_listener(update_listener)

    hass.data[const.DOMAIN][config_entry.entry_id] = {
        const.COORDINATOR: coordinator,
        const.COORDINATOR_OBSERVATION: coordinator_observation,
        const.UNDO_UPDATE_LISTENER: undo_listener,
    }

    await hass.config_entries.async_forward_entry_setups(
        config_entry,
        PLATFORMS
    )

    return True


async def async_unload_entry(hass, config_entry):
    """Unload an FMI config entry."""
    await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)

    hass.data[const.DOMAIN][config_entry.entry_id][const.UNDO_UPDATE_LISTENER]()
    hass.data[const.DOMAIN].pop(config_entry.entry_id)

    return True


async def update_listener(hass, config_entry):
    """Update FMI listener."""
    await hass.config_entries.async_reload(config_entry.entry_id)


class FMILightningStruct():
    """Lightning data structure"""

    def __init__(self, time_val, location, distance, strikes,
                 peak_current, cloud_cover, ellipse_major):
        """Initialize the lightning parameters."""
        # self.time = time_val
        self.time = local_display_time(time_val, dt_util.as_local)
        self.location = location
        self.distance = float(f"{float(distance):.2f}")
        self.strikes = int(strikes)
        self.peak_current = float(peak_current)
        self.cloud_cover = float(cloud_cover)
        self.ellipse_major = float(ellipse_major)


class FMIMareoStruct():
    """Mareo data structure"""

    class SeaLevelData():
        def __init__(self, time_val: str, sea_level: float):
            """Initialize the sea level data."""
            self.time = local_display_time(time_val, dt_util.as_local)
            self.sea_level = float(sea_level)

    def __init__(self):
        """Initialize the sea height data."""
        self.sea_levels: list[FMIMareoStruct.SeaLevelData] = []

    def size(self) -> int:
        """Get the size of the sea level data."""
        return len(self.sea_levels)

    def get_values(self) -> list[SeaLevelData]:
        """Get the sea level values."""
        return list(self.sea_levels)

    def append(self, sea_level_data: SeaLevelData):
        """Clear the sea level data."""
        self.sea_levels.append(sea_level_data)

    def append_values(self, time_val, sea_level):
        """Clear the sea level data."""
        sea_level_data = FMIMareoStruct.SeaLevelData(time_val, sea_level)
        self.sea_levels.append(sea_level_data)


class FMIDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching FMI data API."""

    def __init__(self, hass: HomeAssistant, session, config_entry,
                 update_interval=const.FORECAST_UPDATE_INTERVAL,
                 unique_id_add="", name=""):
        """Initialize."""
        _ = session

        self.logger = const.LOGGER.getChild("coordinator")

        self._hass = hass
        self.latitude = latitude = config_entry.data[CONF_LATITUDE]
        self.longitude = longitude = config_entry.data[CONF_LONGITUDE]
        self.unique_id = str(latitude) + ":" + str(longitude) + unique_id_add

        self.logger.debug(f"Using latitude: {latitude} and longitude: {longitude}")

        _options: dict = config_entry.options

        self.time_step = int(_options.get(CONF_OFFSET, const.FORECAST_OFFSET[0]))
        self.forecast_points = (
            int(_options.get(const.CONF_FORECAST_DAYS, const.DAYS_DEFAULT)
                ) * 24 // self.time_step)
        self.min_temperature = float(_options.get(
            const.CONF_MIN_TEMP, const.TEMP_MIN_DEFAULT))
        self.max_temperature = float(_options.get(
            const.CONF_MAX_TEMP, const.TEMP_MAX_DEFAULT))
        self.min_humidity = float(_options.get(
            const.CONF_MIN_HUMIDITY, const.HUMIDITY_MIN_DEFAULT))
        self.max_humidity = float(_options.get(
            const.CONF_MAX_HUMIDITY, const.HUMIDITY_MAX_DEFAULT))
        self.min_wind_speed = float(_options.get(
            const.CONF_MIN_WIND_SPEED, const.WIND_SPEED_MIN_DEFAULT))
        self.max_wind_speed = float(_options.get(
            const.CONF_MAX_WIND_SPEED, const.WIND_SPEED_MAX_DEFAULT))
        self.min_precip = float(_options.get(
            const.CONF_MIN_PRECIPITATION, const.PRECIPITATION_MIN_DEFAULT))
        self.max_precip = float(_options.get(
            const.CONF_MAX_PRECIPITATION, const.PRECIPITATION_MAX_DEFAULT))
        self.daily_mode = bool(_options.get(
            const.CONF_DAILY_MODE, const.DAILY_MODE_DEFAULT))
        self.lightning_mode = bool(_options.get(
            const.CONF_LIGHTNING, const.LIGHTNING_DEFAULT))
        self.lightning_radius = int(_options.get(
            const.CONF_LIGHTNING_DISTANCE, const.BOUNDING_BOX_HALF_SIDE_KM))

        # Observation data if the station id is set and valid
        self.observation: typing.Optional[fmi_models.Weather] = None
        # Current weather based on forecast for selected coordinates
        # Note: this is an estimation received from FMI
        self.current: typing.Optional[fmi_models.Weather] = None
        # Next day(s) forecasts
        self.forecast: typing.Optional[fmi_models.Forecast] = None

        # Best Time Attributes derived based on forecast weather data
        self.best_time: typing.Optional[datetime] = None
        self.best_temperature: typing.Optional[float] = None
        self.best_humidity: typing.Optional[float] = None
        self.best_wind_speed: typing.Optional[float] = None
        self.best_precipitation: typing.Optional[float] = None
        self.best_state: typing.Optional[str] = None

        # Lightning strikes
        self.lightning_data: typing.Optional[list[FMILightningStruct]] = None

        # Mareo
        self.mareo_data: typing.Optional[FMIMareoStruct] = None

        # Reverse geocoding is optional and limited to one new strike per poll.
        # Keep the cache across refreshes to avoid repeated Nominatim queries.
        self._geolocator = None
        self._reverse_geocoder = CachedReverseGeocoder(self._reverse_address)

        name = name if name else const.DOMAIN

        self.logger.debug(f"FMI {name}: Data will be updated every {update_interval} min")

        super().__init__(hass, self.logger, config_entry=config_entry,
                         name=name, update_interval=update_interval)

    def get_observation(self) -> typing.Optional[fmi_models.Weather]:
        """Return the current observation data."""
        return self.observation

    def get_weather(self) -> typing.Optional[fmi_models.Weather]:
        """Return the current weather data."""
        return self.current

    def get_forecasts(self) -> typing.List[fmi_models.WeatherData]:
        """Return the current forecast data."""
        if self.forecast is None or not has_future_forecast(self.forecast):
            return []
        return self.forecast.forecasts

    def get_current_place(self) -> typing.Optional[str]:
        """Return the current place."""
        if self.current is not None and hasattr(self.current, 'place'):
            return self.current.place
        return None

    def __update_best_weather_condition(self):

        _weather = self.get_weather()

        if _weather is None:
            return

        _forecasts = self.get_forecasts()

        curr_date = dt_util.now().date()

        # Init values
        self.best_state = const.BEST_CONDITION_NOT_AVAIL
        self.best_time = dt_util.as_local(_weather.data.time)
        self.best_temperature = _weather.data.temperature.value
        self.best_humidity = _weather.data.humidity.value
        self.best_wind_speed = _weather.data.wind_speed.value
        self.best_precipitation = _weather.data.precipitation_amount.value

        for forecast in _forecasts:
            local_time = dt_util.as_local(forecast.time)

            if local_time.date() != curr_date:
                # Compare complete local calendar dates (including year end).
                continue

            if (forecast.symbol.value not in const.BEST_COND_SYMBOLS or
                    (wind_speed := forecast.wind_speed.value) is None or
                    wind_speed < self.min_wind_speed or
                    wind_speed > self.max_wind_speed):
                continue

            temperature = forecast.temperature.value
            if (temperature is None or
                    temperature < self.min_temperature or
                    temperature > self.max_temperature):
                continue

            if ((humidity := forecast.humidity.value) is None or
                    humidity < self.min_humidity or
                    humidity > self.max_humidity):
                continue

            if ((precipitation_amount := forecast.precipitation_amount.value) is None or
                    precipitation_amount < self.min_precip or
                    precipitation_amount > self.max_precip):
                continue

            # What more can you ask for?
            # Compare with temperature value already stored and
            # update if necessary

            self.best_state = const.BEST_CONDITION_AVAIL

            if self.best_temperature is None or temperature > self.best_temperature:
                self.best_time = local_time
                self.best_temperature = temperature
                self.best_humidity = forecast.humidity.value
                self.best_wind_speed = forecast.wind_speed.value
                self.best_precipitation = forecast.precipitation_amount.value

    def _reverse_address(self, latitude, longitude):
        """Reverse lookup called only through the rate-limited geocoder."""
        if self._geolocator is None:
            self._geolocator = Nominatim(user_agent="fmi_hass_custom")
        return self._geolocator.reverse(
            f"{latitude}, {longitude}", language="en", timeout=3
        )

    def __get_lightning_url(self):
        """Fetch an FMI lightning coverage using a timezone-correct UTC URL."""
        start_time = utc_time_parameter(
            lookback=timedelta(days=const.LIGHTNING_DAYS_LIMIT)
        )
        box = utils.get_bounding_box(
            self.latitude, self.longitude, half_side_in_km=self.lightning_radius
        )
        bbox = (
            f"bbox={box.lon_min},{box.lat_min},{box.lon_max},{box.lat_max}"
        )
        url = f"{const.LIGHTNING_GET_URL}{start_time}&{bbox}&"
        response = requests.get(url, timeout=const.TIMEOUT_LIGHTNING_PULL_IN_SECS)
        response.raise_for_status()
        return response.content

    def __update_lightning_strikes(self):
        """Parse coverage by XML field name and resolve at most one new address."""
        payload = self.__get_lightning_url()
        deadline = time.monotonic() + const.LIGHTNING_LOOP_TIMEOUT_IN_SECS
        strikes = parse_lightning(
            payload, (self.latitude, self.longitude),
            limit=const.LIGHTNING_LIMIT, deadline=deadline
        )
        results = []
        attempted_lookup = False
        for strike in strikes:
            latitude, longitude = strike["latitude"], strike["longitude"]
            location = f"{latitude}, {longitude}"
            # Keep cached addresses without sending extra HTTP requests.
            cached = self._reverse_geocoder.get_cached(latitude, longitude)
            if cached:
                location = cached
            elif not attempted_lookup:
                attempted_lookup = True
                location = (
                    self._reverse_geocoder.lookup(latitude, longitude)
                    or location
                )
            results.append(FMILightningStruct(
                time_val=strike["time"].isoformat(),
                location=location,
                distance=strike["distance"],
                strikes=strike["strikes"],
                peak_current=strike["peak_current"],
                cloud_cover=strike["cloud_cover"],
                ellipse_major=strike["ellipse_major"],
            ))
        return results

    def __update_mareo_data(self):
        """Parse FMI SeaLevel values by XML name; ignore the N2000 datum."""
        start_time = utc_time_parameter()
        latlon = f"latlon={self.latitude},{self.longitude}"
        url = f"{const.MAREO_GET_URL}{latlon}&{start_time}&"
        response = requests.get(url, timeout=const.TIMEOUT_MAREO_PULL_IN_SECS)
        response.raise_for_status()
        rows = parse_sea_level(response.content)
        if not rows:
            self.logger.debug("FMI: SeaLevel data not available")
            return None
        result = FMIMareoStruct()
        for timestamp, sea_level in rows:
            result.append_values(timestamp, sea_level)
        return result

    async def _fetch_forecast_weather(self):
        """Fetch current weather data based on estimation (forecast)."""
        try:
            data = await fmi.async_weather_by_coordinates(self.latitude, self.longitude)
        except (fmi_erros.ClientError, fmi_erros.ServerError) as error:
            self.logger.error("FMI: unable to fetch weather data! error %s", error)
            return None
        return data

    async def _fetch_forecast(self):
        """Refresh optional forecast without retaining an outdated snapshot."""
        if not self.forecast_points:
            self.forecast = None
            return
        try:
            async with timeout(const.TIMEOUT_OPTIONAL_FORECAST_IN_SEC):
                forecast = await fmi.async_forecast_by_coordinates(
                    self.latitude, self.longitude, self.time_step,
                    self.forecast_points)
        except (fmi_erros.ClientError, fmi_erros.ServerError, TimeoutError) as error:
            self.logger.warning("FMI forecast is unavailable: %s", error)
            self.forecast = None
            return
        # Broad handling is deliberate at this optional-source boundary.
        # pylint: disable-next=broad-exception-caught
        except Exception:  # noqa: BLE001
            self.logger.exception("FMI forecast request failed unexpectedly")
            self.forecast = None
            return

        if not has_future_forecast(forecast):
            self.logger.warning("FMI forecast contains no future data")
            self.forecast = None
            return
        self.forecast = forecast

    async def _refresh_optional_source(self, func, name):
        """Run blocking optional source code, isolating errors and timeouts.

        Workers return data rather than changing attributes; a timed-out
        executor thread cannot overwrite a newer refresh after cancellation.
        """
        try:
            async with timeout(const.TIMEOUT_OPTIONAL_SOURCE_IN_SEC):
                return await self._hass.async_add_executor_job(func)
        # Broad handling is deliberate at this optional-source boundary.
        # pylint: disable-next=broad-exception-caught
        except Exception:  # noqa: BLE001
            self.logger.exception("FMI optional source %s is unavailable", name)
            return None

    async def _async_update_data(self):
        """Update core weather first; degrade independent sources separately."""
        try:
            async with timeout(const.TIMEOUT_FMI_INTEG_IN_SEC):
                weather_data = await self._fetch_forecast_weather()
                if not is_fresh_weather(weather_data, const.CURRENT_MAX_AGE):
                    raise UpdateFailed("FMI current weather is missing or stale")
        except (TimeoutError, UpdateFailed) as error:
            # CoordinatorEntity marks core weather/sensors unavailable on failure.
            raise UpdateFailed(error) from error

        self.current = weather_data
        await self._fetch_forecast()

        try:
            await self._hass.async_add_executor_job(
                self.__update_best_weather_condition
            )
        # Broad handling is deliberate at this optional-source boundary.
        # pylint: disable-next=broad-exception-caught
        except Exception:  # noqa: BLE001
            self.logger.exception("FMI best-time calculation failed")
            self.best_time = None
            self.best_temperature = None
            self.best_humidity = None
            self.best_wind_speed = None
            self.best_precipitation = None
            self.best_state = const.BEST_CONDITION_NOT_AVAIL

        # Optional failures must not make the current-weather entity unavailable.
        if self.lightning_mode and self.lightning_radius:
            self.lightning_data = await self._refresh_optional_source(
                self.__update_lightning_strikes, "lightning"
            )
        else:
            self.lightning_data = None
        self.mareo_data = await self._refresh_optional_source(
            self.__update_mareo_data, "sea level"
        )

        return {"current": self.current}


class FMIObservationUpdateCoordinator(FMIDataUpdateCoordinator):

    def __init__(self, hass: HomeAssistant, session, config_entry,
                 update_interval=const.OBSERVATION_UPDATE_INTERVAL):

        self.observation_station_id = int(
            config_entry.options.get(const.CONF_OBSERVATION_STATION, 0))
        if not self.observation_station_id:
            raise AttributeError("observation not configured!")

        name = f"{const.DOMAIN} Observation"

        super().__init__(hass, session, config_entry, update_interval,
                         unique_id_add="_observation", name=name)

    async def _fetch_observation(self):
        """Fetch the latest obsevation data from specified station."""
        if not self.observation_station_id:
            return None
        try:
            observation = await fmi.async_observation_by_station_id(
                self.observation_station_id)
        except Exception as error:  # noqa: BLE001
            self.observation = None
            raise UpdateFailed(
                f"FMI observation station {self.observation_station_id} failed"
            ) from error
        self.observation = observation

    async def _async_update_data(self):
        """Update observation data via Open API."""
        self.logger.debug("FMI: Updating observation data for station %d",
                          self.observation_station_id)
        try:
            async with timeout(const.TIMEOUT_FMI_INTEG_IN_SEC):
                await self._fetch_observation()
                if not is_fresh_weather(
                    self.observation, const.OBSERVATION_MAX_AGE,
                    max_future=timedelta(minutes=15)
                ):
                    raise UpdateFailed("FMI observation is missing or stale")
        except (TimeoutError, UpdateFailed) as error:
            self.observation = None
            raise UpdateFailed(error) from error
        return {"observation": self.observation}
