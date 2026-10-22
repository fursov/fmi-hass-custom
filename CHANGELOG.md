# Changelog

This document tracks changes to the **FMI Home Assistant integration**, not
the independent `fmi-weather-client` Python package. Entries retain technical
notes from the staged modernization PRs; the release version below is the
integration's `manifest.json` version.

## v0.9.0 — release candidate (not yet published)

The next release includes the canonical HACS integration layout introduced
in merged PR9 and the FMI client 1.0.0 dependency update prepared in PR10.
Existing configuration entries and entity IDs are intended to remain stable.

### Standard repository layout (PR9)

The integration's production code, `manifest.json`, `strings.json` and
translations live in `custom_components/fmi/`. HACS installs this directory
to `<HA configuration directory>/custom_components/fmi/`, without the former
`content_in_root: true` setting. Only repository-level documentation, CI
configuration, HACS metadata and tests remain at the repository root.

The domain, config entry, entity names, unique IDs, option names and the
manifest version are unchanged by this move. Existing HACS installations should not need to be removed and re-added;
install the next tagged release containing the standard layout. Manual installations should copy only the new
`custom_components/fmi/` contents, replacing the old files in place.

PR9 was merged after the published v0.8.0 tag. The new directory layout is
scheduled to ship with v0.9.0.

### FMI client compatibility (PR10)

The integration now pins `fmi-weather-client==1.0.0` in its manifest
and CI requirements instead of 0.7.0. The Python package is versioned
independently from this Home Assistant integration; the integration's
manifest `version` is raised to `0.9.0` for the next integration release.

The PR adds an import/signature/data-model contract check for the **real**
installed package and a Home Assistant test that uses actual client
`Weather`, `Forecast`, `WeatherData` and `Value` objects rather than
only stand-ins. FMI network requests remain mocked. Real FMI weather, forecast and station responses still require an installed
Home Assistant smoke test before publishing a HACS release.

## v0.8.0 — released 2026-10-22

[Published GitHub release](https://github.com/fursov/fmi-hass-custom/releases/tag/v0.8.0).
PR1–PR8 modernized integration behavior and testing while preserving
config-entry and entity identities.

### Release v0.8.0 (PR8)

Version **v0.8.0** introduced blocking integration tests running the real
Home Assistant config-entry, sensor, weather, registry and service lifecycle
against locally mocked FMI API responses. The existing fast offline suite
remains independent. The release checklist documents the validation performed.
See [release checklist](RELEASE_CHECKLIST_0.8.0.md).

PR8 replaces the third-party `async_timeout` import with Python's built-in
`asyncio.timeout` (available since Python 3.11); Home Assistant no longer has
to install that dependency for FMI to load.

### Configuration entry modernization (PR7)

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
At this point the manifest still contained `0.6.2`; the version was
corrected to `0.8.0` in PR8.

The minimum supported Home Assistant version was not declared. HA runtime
integration tests were added in PR8.

### FMI WFS XML and geocoding (PR6)

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
live FMI service output. Test against actual FMI responses and HA timezone
settings before relying on production lightning and sea-level observations.

### Sensor entities (PR5)

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

### Weather forecasts (PR4)

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

### FMI source availability (PR3)

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
revisited based on real FMI update behavior. No entity IDs or option keys were changed. Full HA integration-test coverage
was subsequently added in PR8.

### Coordinator lifecycle (PR2)

Migrated weather and sensor entities to `CoordinatorEntity`, using Home
Assistant-managed listeners instead of direct coordinator subscriptions.
Preserved entity identifiers while establishing proper update propagation.

### Offline characterization baseline (PR1)

Added the offline behavior and entity-identity regression suite and CI lint
baseline. Later PRs expanded it to native sensor/forecast, XML parsing,
config-flow and Home Assistant integration tests.

## Earlier releases

The preceding published tags include
[v0.7.2](https://github.com/fursov/fmi-hass-custom/releases/tag/v0.7.2),
[v0.7.1](https://github.com/fursov/fmi-hass-custom/releases/tag/v0.7.1) and
[v0.7.0](https://github.com/fursov/fmi-hass-custom/releases/tag/v0.7.0).
See the GitHub release pages for their original notes.
