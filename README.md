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
    3. Do steps 5-7 from "Manual installation" instructions below

## Manual installation

    1. Using a tool of choice open the directory (folder) for HA configuration (where you find configuration YAML file)
    2. If `custom_components` directory does not exist, create one
    3. In the `custom_components` directory create a new folder called "fmi"
    4. Download all the files from the this repository and place the files in the new directory created.
       If using `git clone` command, ensure that the local directory is renamed from `fmi-hass-custom` to `fmi`.
       Either way, all files of the repo/download should be in `<HA configuration location>/custom_components/fmi/`
    5. Restart Home Assistant
    6. Install integration from UI (Settings --> Devices & services --> Add integration --> Search for fmi)
    7. Specify the latitude and longitude (default values are picked from the Home Assistant configuration)

## Weather and sensors

In addition to the weather platform, default sensors include different weather conditions (temperature, humidity, wind speed, cloud coverage, etc.),
"best time of the day" (based on preferences), closest lightning strikes and sea level forecasts.
Preferences for "best time of the day" can be tweaked by changing the values via UI
(Settings --> Devices & services --> Integrations --> Finnish Meteorological Institute --> \<weather location\> --> Configure).
For tracking the weather and sensors of another location follow steps 6-7 of "Manual installation" with the latitude and longitude of the location.

Based on the latitude and longitude, location name is derived by reverse geo-coding. Sensors are then grouped based on the derived location name.
For example `weather.<place_name>`, `sensor.<place_name>_temperature`, `sensor.<place_name>_humidity`, etc.

Integration options (Settings --> Devices & services --> Integrations --> Finnish Meteorological Institute --> \<weather location\> --> Configure)
include forecast interval and other weather parameters. These weather parameters are used to
determine the "Best Time Of The Day". Additionally there is are two options:

- Set "Daily mode" that will provide a view of minimum and maximum temperatures for the forecasts. By default this is set to True.
- Set "Lightning sensor" to display closes lightning strikes within a bounding box of 500 kilometers. By default this is set to False.

## Original author

Anand Radhakrishnan [@anand-p-r](https://github.com/anand-p-r)

## FMI source availability (PR3)

The current weather estimate is required for the main weather coordinator.
An unavailable or outdated current weather estimate marks that coordinator's
entities unavailable until a successful refresh. A response older than 3 hours
(or timestamped more than 2 hours in the future) is treated as stale.

Forecast retrieval, lightning and sea-level queries are **optional**. Their
failures do not prevent current-weather updates. Stale forecasts are cleared;
forecast-dependent sensors become unavailable when the requested forecast is
missing, but the place and best-time sensors can still use current weather.
Lightning and sea-level sensors become unavailable when their own queries fail.
An empty, successful lightning result means no recorded strikes, not an API
failure.

Configured observation stations refresh independently at 10-minute intervals.
A failed first station refresh no longer blocks integration setup; its weather
entity remains unavailable until the station recovers. Observations older than
2 hours (or over 15 minutes in the future) are rejected.

The source freshness thresholds are conservative safety defaults and may be
revisited based on real FMI update behavior. No entity IDs or option keys have
changed. Full Home Assistant runtime coverage remains a follow-up item.

## Weather forecasts (PR4)

Both hourly and daily forecasts are available via the Home Assistant
`weather.get_forecasts` action on the main weather entity. For backward
compatibility, the optional `weather.*_daily` entity is retained; the type
requested by `get_forecasts` takes precedence over that entity's legacy mode.
The station observation entity does not advertise forecasts.

All forecast timestamps use the Home Assistant configured local timezone.
Daily forecasts start at local midnight (including DST transitions); high/low
temperatures ignore missing or invalid values, and the daily condition is
represented by the sample closest to local noon. Hourly forecasts keep native
units and FMI's original sample cadence without interpolating missing hours.

For hourly FMI sampling, daily precipitation is the sum of the available
1-hour accumulation fields (mm). If the configured FMI timestep is greater
than one hour, daily precipitation is unknown rather than extrapolated or
incorrectly summed. A partly available day yields a partly available total.

## Sensor entities (PR5)

FMI sensors now use the Home Assistant `SensorEntity` API and
`SensorEntityDescription` metadata. Names, unique IDs, attributes and options
remain compatible with existing dashboards. Native sensor values preserve
finite numbers including zero; missing/invalid numbers become unknown. Source
or coordinator failures continue to appear as unavailable.

Current-weather numeric sensors offer measurement statistics at the one-hour
FMI step; future forecasts and sea-level forecasts do not masquerade as current
measurements. Rain remains FMI precipitation intensity in mm/h and sea level
remains cm. Home Assistant may convert native units based on the user settings
and existing entity registry preferences.

## FMI WFS XML and geocoding (PR6)

Lightning and sea-level WFS requests now use genuine UTC `starttime=...Z`
values, including around daylight-saving changes. Results are parsed using
XML element local names rather than nested child numbers or fragile newline
positions. WFS `ExceptionReport` responses (including HTTP 200) and HTTP
errors mark the optional source unavailable without interrupting current
weather. FMI `SeaLevelN2000` remains excluded for compatibility.

Lightning coordinates and strike counts still populate the same sensor
attributes. The distance uses a local great-circle calculation and does not
require reverse geocoding. Nominatim addresses are optional; no more than
one uncached location is looked up during a refresh, successful addresses
are cached, and all integration instances enforce a 1.1-second request
spacing. If geocoding is unavailable, the location string is the GPS
latitude/longitude. This also avoids repeated requests to third parties.

Displayed timestamps retain the original `YYYY-MM-DD HH:MM` format, now
converted from FMI's UTC observations to the configured Home Assistant
timezone. The best-time-of-day calculation uses whole local calendar
dates, including year boundaries.

The new XML fixtures are **synthetic WFS-shaped responses**, not recorded
live FMI service output. Test against an actual FMI response and your HA
timezone before merging this PR.

## Configuration entry modernization (PR7)

The integration uses `ConfigEntry.runtime_data` to keep the weather and
optional station coordinators. There are no longer per-entry coordinator
dictionaries in `hass.data`. Home Assistant owns their lifetime and the
options update-listener unsubscribe callback; the same existing entry,
entity identifiers, and option keys continue to work after an upgrade.

Configuration flow validation uses the FMI asynchronous weather endpoint
with a 15-second timeout. A network problem shows a translated connection
error on the form instead of exiting the flow. The options flow uses
Home Assistant's built-in `config_entry` property and retains the existing
reload-on-change behavior.

Configuration forms and all 14 option labels are available in English,
Finnish and Russian. Documentation, maintainer, issue tracker and third-party runtime dependencies
are identified in the integration manifest (Home Assistant core libraries are
not duplicated). Hassfest validation is now a blocking CI check.
The version remains `0.6.2` until the release PR.

The minimal supported Home Assistant version is not declared in this PR:
while current APIs are targeted, an end-to-end runtime test and version
compatibility matrix remain part of PR8.
