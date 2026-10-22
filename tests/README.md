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
