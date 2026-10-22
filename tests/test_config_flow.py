"""Offline PR7 tests: config flows, runtime_data and translation contracts."""

import ast
import asyncio
import json
import logging
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from conftest import SOURCE_ROOT, source_definition


class FMIClientError(Exception):
    """Synthetic library error."""


class FMIServerError(Exception):
    """Synthetic server error."""


class ConfigEntryNotReady(Exception):
    """Synthetic Home Assistant entry retry."""


def _constants():
    """Evaluate the real constant assignments without Home Assistant imports."""
    source = SOURCE_ROOT / "const.py"
    node = ast.parse(source.read_text(encoding="utf-8"))
    assignments = [item for item in node.body if isinstance(item, ast.Assign)]
    program = ast.fix_missing_locations(ast.Module(
        body=assignments, type_ignores=[]
    ))
    scope = {
        "range": range, "list": list, "logging": logging,
        "timedelta": timedelta, "__package__": "fmi",
    }
    exec(compile(program, str(source), "exec"), scope)  # noqa: S102
    return SimpleNamespace(**scope)


def _validation(api, *, timeout=0.1):
    const = _constants()
    const.TIMEOUT_CONFIG_FLOW_IN_SEC = timeout
    return source_definition(
        "config_flow.py", "validate_user_config",
        namespace={
            "core": SimpleNamespace(HomeAssistant=object),
            "ha_const": SimpleNamespace(
                CONF_LATITUDE="latitude", CONF_LONGITUDE="longitude"
            ),
            "asyncio": asyncio,
            "fmi_client": SimpleNamespace(async_weather_by_coordinates=api),
            "fmi_errors": SimpleNamespace(
                ClientError=FMIClientError, ServerError=FMIServerError
            ),
            "const": const,
        },
    )


def test_validation_is_nonblocking_and_preserves_location_title():
    api = AsyncMock(return_value=SimpleNamespace(place="Helsinki"))
    check = _validation(api)
    data = {"name": "Home", "latitude": 60.17, "longitude": 24.94}
    result = asyncio.run(check(None, data))
    assert result == {"place": "Helsinki", "err": ""}
    api.assert_awaited_once_with(60.17, 24.94)


@pytest.mark.parametrize(
    ("exception", "code"),
    [
        (FMIClientError("bad coordinates"), "cannot_connect"),
        (FMIServerError("server failed"), "cannot_connect"),
        (OSError("network down"), "cannot_connect"),
        (RuntimeError("unexpected"), "unknown"),
    ],
)
def test_config_validation_errors_use_translated_codes(exception, code):
    check = _validation(AsyncMock(side_effect=exception))
    result = asyncio.run(check(None, {
        "latitude": 60.17, "longitude": 24.94
    }))
    assert result == {"place": None, "err": code}


def test_validation_rejects_empty_location():
    check = _validation(AsyncMock(return_value=SimpleNamespace(place=None)))
    assert asyncio.run(check(None, {
        "latitude": 60.17, "longitude": 24.94
    })) == {"place": None, "err": "unknown"}


def test_validation_times_out_without_hanging_flow():
    async def slow(_lat, _lon):
        await asyncio.sleep(0.02)
        return SimpleNamespace(place="Helsinki")

    check = _validation(slow, timeout=0.001)
    assert asyncio.run(check(None, {
        "latitude": 60.17, "longitude": 24.94
    }))["err"] == "cannot_connect"


def _flow_scopes():
    const = _constants()
    keys = SimpleNamespace(
        CONF_NAME="name", CONF_LATITUDE="latitude",
        CONF_LONGITUDE="longitude", CONF_OFFSET="offset"
    )

    # Represent voluptuous field-default descriptors while avoiding dependency.
    vol = SimpleNamespace(
        Required=lambda key, default=None: (key, default),
        Optional=lambda key, default=None: (key, default),
        Schema=lambda value: value,
        In=lambda choices: tuple(choices),
    )
    cv = SimpleNamespace(
        latitude=float, longitude=float,
        boolean=bool, small_float=float, positive_int=int,
    )
    return {
        "const": const, "ha_const": keys, "vol": vol, "cv": cv,
    }


def _options():
    scope = _flow_scopes()
    Options = source_definition(
        "config_flow.py", "FMIOptionsFlowHandler",
        base="object", methods=["async_step_init", "async_step_user"],
        namespace=scope,
    )
    handler = Options()
    handler.config_entry = SimpleNamespace(options={})
    handler.async_show_form = lambda **kwargs: {"kind": "form", **kwargs}
    handler.async_create_entry = lambda **kwargs: {"kind": "entry", **kwargs}
    return handler


def test_options_flow_uses_framework_config_entry_not_legacy_override():
    tree = ast.parse((SOURCE_ROOT / "config_flow.py").read_text(encoding="utf-8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
               and n.name == "FMIOptionsFlowHandler")
    assert not any(isinstance(n, ast.FunctionDef) and n.name == "config_entry"
                   for n in cls.body)
    assert any(isinstance(n, ast.Attribute) and n.attr == "OptionsFlow"
               for n in cls.bases)


def test_options_form_preserves_all_fourteen_legacy_keys_and_defaults():
    options = _options()
    const = _constants()
    saved = {
        const.CONF_FORECAST_DAYS: 6,
        const.CONF_LIGHTNING: True,
        const.CONF_OBSERVATION_STATION: 101,
        "offset": 3,
    }
    options.config_entry.options = saved
    form = asyncio.run(options.async_step_init())
    assert form["kind"] == "form"
    assert form["step_id"] == "user"
    defaults = {
        item[0]: item[1] for item in form["data_schema"]
    }
    assert len(defaults) == 14
    assert defaults["forecast_days"] == 6
    assert defaults["lightning_sensor"] is True
    assert defaults["observation_station_id"] == 101
    assert defaults["offset"] == 3
    assert defaults["daily_mode"] is False


def test_options_flow_saves_user_values_without_renaming_keys():
    options = _options()
    provided = {"forecast_days": 5, "offset": 6, "lightning_sensor": True}
    assert asyncio.run(options.async_step_user(provided)) == {
        "kind": "entry", "title": "FMI Options", "data": provided
    }


def test_config_entry_uses_original_unique_id_and_location():
    scope = _flow_scopes()
    BaseFlow = source_definition(
        "config_flow.py", "FMIConfigFlowHandler",
        base="object", methods=["async_step_user"],
        namespace={
            **scope,
            "validate_user_config": AsyncMock(return_value={
                "place": "Helsinki", "err": ""
            }),
            "base_unique_id": lambda lat, lon: f"{lat}_{lon}",
        },
    )
    handler = BaseFlow()
    handler.hass = SimpleNamespace(config=SimpleNamespace(
        latitude=60.17, longitude=24.94
    ))
    handler.async_set_unique_id = AsyncMock()
    handler._abort_if_unique_id_configured = Mock()
    handler.async_create_entry = lambda **kwargs: kwargs
    handler.async_show_form = lambda **kwargs: kwargs
    data = {"name": "Home", "latitude": 60.17, "longitude": 24.94}
    result = asyncio.run(handler.async_step_user(data))
    assert result == {"title": "Helsinki", "data": data}
    handler.async_set_unique_id.assert_awaited_once_with("60.17_24.94")
    handler._abort_if_unique_id_configured.assert_called_once_with()


def test_config_validation_failure_shows_localized_error_key():
    scope = _flow_scopes()
    Flow = source_definition(
        "config_flow.py", "FMIConfigFlowHandler",
        base="object", methods=["async_step_user"],
        namespace={
            **scope,
            "validate_user_config": AsyncMock(return_value={
                "place": None, "err": "cannot_connect"
            }),
            "base_unique_id": lambda lat, lon: f"{lat}_{lon}",
        },
    )
    handler = Flow()
    handler.hass = SimpleNamespace(config=SimpleNamespace(
        latitude=60.17, longitude=24.94
    ))
    handler.async_set_unique_id = AsyncMock()
    handler._abort_if_unique_id_configured = Mock()
    handler.async_show_form = lambda **kwargs: kwargs
    result = asyncio.run(handler.async_step_user({
        "name": "Home", "latitude": 60.17, "longitude": 24.94
    }))
    assert result["errors"] == {"base": "cannot_connect"}


class FakeCoordinator:
    """Fake for core weather coordinator."""

    last_update_success = True

    def __init__(self, _hass, _session, _entry):
        pass

    async def async_config_entry_first_refresh(self):
        return None


class FakeStation(FakeCoordinator):
    """Fake for optional observation station."""


class FakeEntry:
    """ConfigEntry stand-in with HA-managed callback disposal."""

    entry_id = "test-fmi"
    runtime_data = None

    def __init__(self):
        self.callbacks = []

    def add_update_listener(self, callback):
        self.callbacks.append(callback)
        return lambda: self.callbacks.remove(callback)

    def async_on_unload(self, remove):
        self._remove = remove


def _entry_methods(station_class=FakeStation, main_class=FakeCoordinator):
    events = []

    async def forward(entry, platforms):
        events.append(("forward", entry.runtime_data, tuple(platforms)))

    async def unload(entry, platforms):
        events.append(("unload", entry.entry_id, tuple(platforms)))
        return True

    async def reload(entry_id):
        events.append(("reload", entry_id))

    hass = SimpleNamespace(
        config_entries=SimpleNamespace(
            async_forward_entry_setups=forward,
            async_unload_platforms=unload,
            async_reload=reload,
        ),
    )
    data_class = lambda coordinator, observation: SimpleNamespace(
        coordinator=coordinator, observation=observation
    )
    scope = {
        "HomeAssistant": object,
        "FMIConfigEntry": FakeEntry,
        "FMIDataUpdateCoordinator": main_class,
        "FMIObservationUpdateCoordinator": station_class,
        "FMIRuntimeData": data_class,
        "async_get_clientsession": lambda _hass: object(),
        "ConfigEntryNotReady": ConfigEntryNotReady,
        "update_listener": lambda *_args: None,
        "LOGGER": logging.getLogger("test.fmi.entry"),
        "PLATFORMS": ("sensor", "weather"),
    }
    setup = source_definition(
        "__init__.py", "async_setup_entry", namespace=scope
    )
    unload_entry = source_definition(
        "__init__.py", "async_unload_entry", namespace=scope
    )
    update_listener = source_definition(
        "__init__.py", "update_listener", namespace=scope
    )
    return hass, events, setup, unload_entry, update_listener


def test_coordinator_runtime_data_installed_before_platform_setup():
    hass, events, setup, unload, update = _entry_methods()
    entry = FakeEntry()
    assert asyncio.run(setup(hass, entry)) is True
    assert isinstance(entry.runtime_data.coordinator, FakeCoordinator)
    assert isinstance(entry.runtime_data.observation, FakeStation)
    assert len(entry.callbacks) == 1
    assert events[0][0] == "forward"
    assert events[0][1] is entry.runtime_data
    assert asyncio.run(unload(hass, entry)) is True
    assert events[-1][0] == "unload"
    # HA owns callback disposal, not the component's unload handler.
    assert len(entry.callbacks) == 1
    entry._remove()
    assert entry.callbacks == []
    asyncio.run(update(hass, entry))
    assert events[-1] == ("reload", entry.entry_id)


def test_missing_station_still_allows_main_coordinator():
    class NotConfigured(FakeStation):
        def __init__(self, *_args):
            raise AttributeError("not configured")

    hass, events, setup, _, _ = _entry_methods(station_class=NotConfigured)
    entry = FakeEntry()
    assert asyncio.run(setup(hass, entry))
    assert entry.runtime_data.observation is None
    assert events[0][0] == "forward"


def test_config_entry_setup_failure_does_not_publish_runtime_data():
    class NotReady(FakeCoordinator):
        last_update_success = False

    hass, events, setup, _, _ = _entry_methods(main_class=NotReady)
    entry = FakeEntry()
    with pytest.raises(ConfigEntryNotReady):
        asyncio.run(setup(hass, entry))
    assert entry.runtime_data is None
    assert events == []


def test_platform_sources_use_entry_runtime_data_not_hass_data():
    for name in ("sensor.py", "weather.py"):
        source = (SOURCE_ROOT / name).read_text(encoding="utf-8")
        assert "config_entry.runtime_data" in source
        assert "hass.data[const.DOMAIN]" not in source
    source = (SOURCE_ROOT / "__init__.py").read_text(encoding="utf-8")
    assert "config_entry.runtime_data =" in source
    assert "hass.data[const.DOMAIN]" not in source


def test_manifest_tracks_owned_docs_and_direct_dependencies():
    manifest = json.loads((SOURCE_ROOT / "manifest.json").read_text())
    assert manifest["domain"] == "fmi"
    assert manifest["version"] == "0.8.0"
    assert manifest["config_flow"] is True
    assert manifest["documentation"].startswith(
        "https://github.com/fursov/fmi-hass-custom"
    )
    assert "@fursov" in manifest["codeowners"]
    assert "fmi-weather-client==1.0.0" in manifest["requirements"]
    assert not any(item.startswith("requests") for item in manifest["requirements"])


def test_strings_and_all_translations_cover_the_same_flow_keys():
    original = json.loads((SOURCE_ROOT / "strings.json").read_text())
    for name in ("en", "fi", "ru"):
        translated = json.loads(
            (SOURCE_ROOT / "translations" / f"{name}.json").read_text()
        )
        assert set(translated["config"]["error"]) == {
            "cannot_connect", "unknown"
        }
        assert set(translated["config"]["step"]["user"]["data"]) == {
            "name", "latitude", "longitude"
        }
        assert set(translated["options"]["step"]["user"]["data"]) == set(
            original["options"]["step"]["user"]["data"]
        )
        assert len(translated["options"]["step"]["user"]["data"]) == 14
        assert translated["config"]["abort"]["already_configured"]
