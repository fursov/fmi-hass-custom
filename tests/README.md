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

Two known forecast defects are marked `xfail(strict=True)` rather than asserted
as correct behavior. PR4 should fix them and remove the markers.

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
