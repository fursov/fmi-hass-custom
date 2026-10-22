# PR1: offline behavioral baseline

These tests deliberately run **without Home Assistant, HTTP calls or FMI servers**.
They load selected original functions/methods from Python's AST and execute them
with explicit minimal dependencies. This avoids changing the existing flat
HACS package layout or coupling the first refactor PR to a moving HA release.

```bash
python -m pip install -r requirements-test.txt
ruff check tests
python -m compileall -q tests
bash .github/scripts/run-offline-tests.sh
```

What is pinned:

- Existing configuration/option keys and generated `unique_id` values.
- Legacy weather and sensor entity identity formatting.
- Forecast slot shape, max/min temperatures, and empty-list handling.
- Lightning and sea-level model representations.
- A representative **synthetic** WFS exception response for future failures.

**Important:** `tests/fixtures/forecast.json` represents parsed client data, not
a recorded FMI API response. Never use it to assert actual API availability.

PR4 resolved both original forecast xfails. The suite now expects them to pass.

Limitations: AST-isolated tests do not exercise HA lifecycle, registry,
`ConfigFlow`, actual WFS parsing or coordinator scheduling. PR2/PR3 must add
integration tests using `pytest-homeassistant-custom-component` after a target
HA version and installable test package layout are established.

Hassfest is run as an **advisory** job using a staged integration directory.
Any findings there are tracked for the compatibility/manifest follow-up PR;
this stage does not alter the published integration files.

The runner invokes the tests from a temporary directory because recent pytest
versions otherwise collect the repository-root `__init__.py` as a package and
import the live FMI integration. `FMI_SOURCE_ROOT` points the tests back at
the checked-out source files and fixtures. No production package is imported.

## PR2: coordinator lifecycle characterization

`test_coordinator_lifecycle.py` verifies one publication per completed FMI
refresh, no manual `async_set_updated_data` calls during polling, and one
managed listener per entity while it is registered in Home Assistant. It also
checks observation/forecast coordinator isolation and failure behavior.

These tests use a small stand-in for Home Assistant's coordinator/entity
lifecycle and do **not** replace full Home Assistant integration tests.

## PR3: partial failures, freshness and recovery

`test_partial_failures.py` characterizes current-weather/observation age
validation, stale forecast clearing, optional source isolation, station startup
failures and source-specific sensor availability. All tests run offline using
synthetic observations and API stubs; no live FMI queries or Home Assistant
runtime imports are performed.

## PR4: forecast transformation and subscription checks

The pure `forecast.py` module converts timestamped FMI data into native-unit
Home Assistant weather forecasts, using HA-configured local time supplied by the
weather entity. Tests check sorting/deduplication, calendar/year boundaries,
daylight-saving transitions, finite/missing values, max/min temperatures,
hourly precipitation totals, and sparse 3-hour samples. The two known PR1
forecast xfails have been turned into ordinary passing tests.

Forecast totals are sums of available 1-hour accumulations **only when** the
configured FMI query cadence is hourly. An incomplete day contains an
incomplete sum, and 2+-hour cadence returns `None` for daily precipitation
rather than an incorrect full-day estimate.

`weather.*_daily` entity IDs remain unchanged for old installations; each
forecast method now returns its own correct forecast type. Station observation
weather entities expose no forecast support. Websocket forecast subscribers
are notified after coordinator updates.

This suite remains offline; validate the behavior with an installed HA instance
and a live FMI response before merging.

## PR5: native sensor entities

The sensor platform now subclasses `SensorEntity` and publishes values through
`native_value` and `native_unit_of_measurement`. Entity descriptions declare
sensor types and native units while preserving legacy names and identifiers.
Offline tests cover all unique IDs, metadata, missing and nonfinite values,
text states, source availability and source-specific statistics.

These AST-isolated tests do not boot Home Assistant. Check the HA entity
registry and dashboards after upgrading, particularly native unit conversion.

## PR6: offline WFS and reverse-geocoding tests

`test_wfs.py` covers UTC request time generation, conversion to local HA
wall-clock strings across DST, WFS error reports, namespace-independent XML
parsing of FMI lightning coverage and simple SeaLevel elements, malformed
and missing fields, bounded parse deadlines, sorting/selection, cached and
rate-limited optional reverse geocoding, and date boundaries for best time.

The XML fixtures are intentionally synthetic and namespace-shaped, not
captured FMI API responses. The tests require no network connectivity or
third-party geocoding service; add a live-HA/FMI smoke test before merge.

## PR7: config entries, options flow and translations

`test_config_flow.py` checks that FMI validation is asynchronous with an
explicit timeout, errors translate through the Home Assistant `base` form
error, legacy config-entry identity is preserved, the 14 options retain
their persisted keys/defaults, `ConfigEntry.runtime_data` is assigned before
platform setup, and subscription cleanup is owned by Home Assistant. JSON
translation files are checked for English/Finnish/Russian structural parity.

As with earlier stages, these are offline AST characterization tests and
do **not** instantiate a real Home Assistant server. Verify add, configure,
reload, remove and restart workflows manually before merge.

## PR8: real Home Assistant runtime tests

The previous `tests/` suite remains fast, offline and AST-based. PR8 adds a
**separate**, blocking Home Assistant integration job with actual `hass`,
`MockConfigEntry`, entity registry, weather actions and config/option flows.

To run it, use Python 3.14 and install `requirements-ha-test.txt`. Then:

```bash
bash .github/scripts/run-ha-tests.sh
```

The runner copies this repository's *root-layout* production integration to a
temporary `custom_components/fmi` installation. It does not modify the HACS
layout or import the repository root as a package. Only FMI API/geocoding
calls are mocked; Home Assistant lifecycle, registries and services are real.

The HA test dependency is pinned to a known plugin build for reproducible CI.
Check the installed Home Assistant version in the job log; this does not yet
establish support for *all* HA releases or prove live FMI XML compatibility.
