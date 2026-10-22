# fmi-hass-custom

`fmi-hass-custom` is a Home Assistant custom component for weather and sensor platform.
It uses FMI's [open data](https://en.ilmatieteenlaitos.fi/open-data) as a source for
current and forecasted meteorological data for a given location. Data update frequency
is hardcoded to 30 minutes.

## Pre-installation

Follow these instructions if an older manually installed version of the component was in use

    1. Remove all references of the sensor and weather platforms from configuration.yaml
    2. Restart Home Assistant
    3. UI references could also be removed (or they could be the markers to correct when the integration is loaded again using steps below)
    4. Most importantly clear the browser cache where Home Assistant UI is accessed (the new integration may sometimes not show up without this step)

## HACS installation

    1. Install [HACS](https://www.hacs.xyz/)
    2. Add this repository as a [custom repository](https://www.hacs.xyz/docs/faq/custom_repositories/), type is "Integration"
    3. Install FMI from HACS and restart Home Assistant
    4. Add Finnish Meteorological Institute in Settings > Devices & services and enter the location

## Manual installation

    1. Open your Home Assistant configuration directory (where `configuration.yaml` lives).
    2. Create `custom_components` if it does not exist.
    3. Copy the **contents of this repository's `custom_components/fmi/` directory**
       into `<HA configuration directory>/custom_components/fmi/`.
       Do not copy the repository's `tests/`, `.github/`, or `hacs.json`
       into Home Assistant's `fmi/` directory.
    4. Restart Home Assistant.
    5. Add Finnish Meteorological Institute in Settings > Devices & services.
    6. Specify the latitude and longitude of the desired location.

## Weather and sensors

In addition to the weather platform, default sensors include different weather conditions (temperature, humidity, wind speed, cloud coverage, etc.),
"best time of the day" (based on preferences), closest lightning strikes and sea level forecasts.
Preferences for "best time of the day" can be tweaked by changing the values via UI
(Settings --> Devices & services --> Integrations --> Finnish Meteorological Institute --> \<weather location\> --> Configure).
For another location, repeat the integration setup with its latitude and longitude.

Based on the latitude and longitude, location name is derived by reverse geo-coding. Sensors are then grouped based on the derived location name.
For example `weather.<place_name>`, `sensor.<place_name>_temperature`, `sensor.<place_name>_humidity`, etc.

Integration options (Settings --> Devices & services --> Integrations --> Finnish Meteorological Institute --> \<weather location\> --> Configure)
include forecast interval and other weather parameters. These weather parameters are used to
determine the "Best Time Of The Day". Additionally there is are two options:

- Set "Daily mode" that will provide a view of minimum and maximum temperatures for the forecasts. By default this is set to True.
- Set "Lightning sensor" to display closes lightning strikes within a bounding box of 500 kilometers. By default this is set to False.

## Original author

Anand Radhakrishnan [@anand-p-r](https://github.com/anand-p-r)

## Behavior and compatibility

FMI current-weather data, optional forecasts, lightning and sea-level sources
are refreshed independently. If the current weather is stale, the affected
weather entities become unavailable; an optional-source outage does not
prevent unrelated measurements from updating. FMI forecast timestamps use the
Home Assistant local timezone.

Both hourly and daily predictions can be retrieved with the
`weather.get_forecasts` action. The optional legacy daily weather entity and
existing `unique_id` values remain supported.

The integration lives in `custom_components/fmi/`. The minimum supported HA
release has not been declared in HACS metadata; compatibility is verified in
CI against Home Assistant 2026.9.4 using Python 3.14 and offline FMI responses.
Test real FMI weather, optional observation stations and WFS data on your
running Home Assistant installation before releasing changes.

## Release history and development

See [CHANGELOG.md](CHANGELOG.md) for release notes and the detailed PR1–PR10
change history. Testing details are in [tests/README.md](tests/README.md).
For the proposed v0.9.0 release, see
[RELEASE_CHECKLIST_0.9.0.md](RELEASE_CHECKLIST_0.9.0.md).
