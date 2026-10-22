"""Home Assistant config and options flow tests for a staged FMI integration."""

import pytest

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType

DOMAIN = "fmi"


@pytest.mark.asyncio
async def test_user_flow_creates_compatible_config_entry(
    hass, mock_api
):
    """A real HA flow must save the original location identifiers."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={
            "name": "Home", "latitude": 60.17, "longitude": 24.94
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = result["result"]
    assert entry.unique_id == "60.17_24.94"
    assert entry.data["latitude"] == 60.17
    assert entry.data["longitude"] == 24.94
    mock_api.weather.assert_awaited()


@pytest.mark.asyncio
async def test_duplicate_flow_aborts_with_original_location_unique_id(
    hass, make_entry, mock_api
):
    """Upgrades must not create duplicate entries at the same coordinates."""
    _ = mock_api
    make_entry(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
        data={"name": "Other", "latitude": 60.17, "longitude": 24.94},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.asyncio
async def test_options_flow_retains_old_field_names_and_values(
    hass, make_entry, mock_api
):
    """Real OptionsFlow should use framework config_entry and save persisted keys."""
    _ = mock_api
    entry = make_entry(
        hass, options={"offset": 3, "forecast_days": 5}
    )
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "offset": 6,
            "forecast_days": 4,
            "lightning_sensor": False,
            "observation_station_id": 0,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["offset"] == 6
    assert entry.options["forecast_days"] == 4
    assert entry.options["lightning_sensor"] is False
