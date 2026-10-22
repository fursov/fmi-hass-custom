"""Config flow for FMI (Finnish Meteorological Institute) integration."""

import asyncio

import fmi_weather_client as fmi_client
import fmi_weather_client.errors as fmi_errors

import voluptuous as vol

from homeassistant import config_entries, core
import homeassistant.const as ha_const
from homeassistant.helpers import config_validation as cv

from . import base_unique_id
from . import const


async def validate_user_config(hass: core.HomeAssistant, data):
    """Verify that FMI can provide weather for the requested coordinates."""
    _ = hass
    latitude = data[ha_const.CONF_LATITUDE]
    longitude = data[ha_const.CONF_LONGITUDE]

    try:
        async with asyncio.timeout(const.TIMEOUT_CONFIG_FLOW_IN_SEC):
            weather_data = await fmi_client.async_weather_by_coordinates(
                latitude, longitude
            )
        if weather_data is None or not weather_data.place:
            raise ValueError("FMI returned no weather location")
        return {"place": weather_data.place, "err": ""}
    except (fmi_errors.ClientError, fmi_errors.ServerError,
            TimeoutError, OSError) as error:
        const.LOGGER.warning("Unable to connect to FMI: %s", error)
        return {"place": None, "err": "cannot_connect"}
    # Unexpected FMI client failures are reported to the user as an error
    # instead of surfacing an exception that breaks the config flow.
    # pylint: disable-next=broad-exception-caught
    except Exception:  # noqa: BLE001
        const.LOGGER.exception("Unexpected error while validating FMI location")
        return {"place": None, "err": "unknown"}


class FMIConfigFlowHandler(config_entries.ConfigFlow, domain=const.DOMAIN):
    """Config flow handler for FMI."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle user step."""
        # Display an option for the user to provide Lat/Long for the integration
        errors = {}
        if user_input is not None:

            await self.async_set_unique_id(
                base_unique_id(user_input[ha_const.CONF_LATITUDE],
                               user_input[ha_const.CONF_LONGITUDE])
            )
            self._abort_if_unique_id_configured()

            valid = await validate_user_config(self.hass, user_input)

            if valid.get("err", "") == "":
                return self.async_create_entry(title=valid["place"], data=user_input)

            errors["base"] = valid["err"]

        data_schema = vol.Schema(
            {
                vol.Required(ha_const.CONF_NAME, default=const.DEFAULT_NAME): str,
                vol.Required(ha_const.CONF_LATITUDE,
                             default=self.hass.config.latitude): cv.latitude,
                vol.Required(ha_const.CONF_LONGITUDE,
                             default=self.hass.config.longitude): cv.longitude
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    @staticmethod
    @core.callback
    def async_get_options_flow(config_entry):
        """Options callback for FMI."""
        _ = config_entry
        return FMIOptionsFlowHandler()


class FMIOptionsFlowHandler(config_entries.OptionsFlow):
    """Config flow options for FMI."""

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        _ = user_input
        return await self.async_step_user()

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""
        if user_input is not None:
            return self.async_create_entry(title="FMI Options", data=user_input)

        _options = self.config_entry.options

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Optional(const.CONF_FORECAST_DAYS,
                             default=_options.get(
                                 const.CONF_FORECAST_DAYS,
                                 const.DAYS_DEFAULT)): vol.In(const.DAYS_RANGE),
                vol.Optional(ha_const.CONF_OFFSET,
                             default=_options.get(
                                 ha_const.CONF_OFFSET,
                                 const.FORECAST_OFFSET[0])): vol.In(const.FORECAST_OFFSET),
                vol.Optional(const.CONF_MIN_HUMIDITY,
                             default=_options.get(
                                 const.CONF_MIN_HUMIDITY,
                                 const.HUMIDITY_MIN_DEFAULT)): vol.In(const.HUMIDITY_RANGE),
                vol.Optional(const.CONF_MAX_HUMIDITY,
                             default=_options.get(
                                 const.CONF_MAX_HUMIDITY,
                                 const.HUMIDITY_MAX_DEFAULT)): vol.In(const.HUMIDITY_RANGE),
                vol.Optional(const.CONF_MIN_TEMP,
                             default=_options.get(
                                 const.CONF_MIN_TEMP,
                                 const.TEMP_MIN_DEFAULT)): vol.In(const.TEMP_RANGE),
                vol.Optional(const.CONF_MAX_TEMP,
                             default=_options.get(
                                 const.CONF_MAX_TEMP,
                                 const.TEMP_MAX_DEFAULT)): vol.In(const.TEMP_RANGE),
                vol.Optional(const.CONF_MIN_WIND_SPEED,
                             default=_options.get(
                                 const.CONF_MIN_WIND_SPEED,
                                 const.WIND_SPEED_MIN_DEFAULT)): vol.In(const.WIND_SPEED),
                vol.Optional(const.CONF_MAX_WIND_SPEED,
                             default=_options.get(
                                 const.CONF_MAX_WIND_SPEED,
                                 const.WIND_SPEED_MAX_DEFAULT)): vol.In(const.WIND_SPEED),
                vol.Optional(const.CONF_MIN_PRECIPITATION,
                             default=_options.get(
                                 const.CONF_MIN_PRECIPITATION,
                                 const.PRECIPITATION_MIN_DEFAULT)): cv.small_float,
                vol.Optional(const.CONF_MAX_PRECIPITATION,
                             default=_options.get(
                                 const.CONF_MAX_PRECIPITATION,
                                 const.PRECIPITATION_MAX_DEFAULT)): cv.small_float,
                vol.Optional(const.CONF_DAILY_MODE,
                             default=_options.get(
                                 const.CONF_DAILY_MODE,
                                 const.DAILY_MODE_DEFAULT)): cv.boolean,
                vol.Optional(const.CONF_LIGHTNING,
                             default=_options.get(
                                 const.CONF_LIGHTNING,
                                 const.LIGHTNING_DEFAULT)): cv.boolean,
                vol.Optional(const.CONF_LIGHTNING_DISTANCE,
                             default=_options.get(
                                 const.CONF_LIGHTNING_DISTANCE,
                                 const.BOUNDING_BOX_HALF_SIDE_KM)): cv.positive_int,
                vol.Optional(const.CONF_OBSERVATION_STATION,
                             default=_options.get(
                                 const.CONF_OBSERVATION_STATION, 0)): cv.positive_int,
            })
        )
