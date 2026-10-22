"""Offline WFS regression tests: XML schemas, UTC clocks and geocode limits."""

import importlib.util
import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from conftest import ROOT, source_definition


def _wfs():
    """Import the pure XML helper without Home Assistant or network access."""
    spec = importlib.util.spec_from_file_location("fmi_wfs_tests", ROOT / "wfs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fixture(name):
    return (ROOT / "tests/fixtures" / name).read_bytes()


HELSINKI = ZoneInfo("Europe/Helsinki")


def test_utc_starttime_respects_timezone_and_lookback():
    wfs = _wfs()
    local_time = datetime(2026, 10, 22, 15, 20, 30, tzinfo=HELSINKI)
    assert wfs.utc_time_parameter(local_time) == (
        "starttime=2026-10-22T12:20:30Z"
    )
    assert wfs.utc_time_parameter(
        local_time, lookback=timedelta(days=1)
    ) == "starttime=2026-10-21T12:20:30Z"
    assert re.fullmatch(
        r"starttime=\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
        wfs.utc_time_parameter(),
    )


def test_utc_starttime_rejects_naive_datetime():
    with pytest.raises(ValueError, match="timezone aware"):
        _wfs().utc_time_parameter(datetime(2026, 10, 22, 15))


def test_local_time_converts_utc_during_dst_and_preserves_naive_legacy():
    wfs = _wfs()
    convert = lambda stamp: stamp.astimezone(HELSINKI)
    assert wfs.local_display_time(
        "2026-10-25T00:30:00Z", convert
    ) == "2026-10-25 03:30"
    assert wfs.local_display_time(
        "2026-10-25T01:30:00Z", convert
    ) == "2026-10-25 03:30"
    assert wfs.local_display_time(
        "2026-01-01T12:34:00", convert
    ) == "2026-01-01 12:34"


def test_parse_lightning_recovers_coordinates_and_matches_metrics():
    wfs = _wfs()
    strikes = wfs.parse_lightning(
        _fixture("wfs_lightning.xml"), (60.17, 24.94)
    )
    assert len(strikes) == 3
    assert [item["strikes"] for item in strikes] == [2, 1, 1]
    assert strikes[0]["time"] == datetime(2026, 10, 22, 12, 10, tzinfo=UTC)
    assert strikes[0]["peak_current"] == pytest.approx(-3.1)
    assert strikes[2]["distance"] == pytest.approx(0, abs=0.0001)
    assert strikes[2]["cloud_cover"] == pytest.approx(0.1)


def test_lightning_nearest_limit_selected_before_sorting_by_latest():
    records = _wfs().parse_lightning(
        _fixture("wfs_lightning.xml"), (60.17, 24.94), limit=2
    )
    assert len(records) == 2
    assert [x["time"].minute for x in records] == [5, 0]


def test_lightning_whitespace_and_namespace_prefixes_irrelevant():
    payload = _fixture("wfs_lightning.xml").decode()
    payload = payload.replace("gml:", "other:").replace(
        'xmlns:gml="http://www.opengis.net/gml/3.2"',
        'xmlns:other="http://www.opengis.net/gml/3.2"',
    )
    assert len(_wfs().parse_lightning(payload.encode(), (60.17, 24.94))) == 3


def test_lightning_returns_empty_on_empty_feature_collection():
    payload = b'<FeatureCollection xmlns="http://www.opengis.net/wfs/2.0" />'
    assert _wfs().parse_lightning(payload, (60, 25)) == []


def test_lightning_misaligned_xml_is_rejected_not_cross_paired():
    payload = _fixture("wfs_lightning.xml").decode().replace(
        "1 4.0 0.3 4.0", ""
    )
    with pytest.raises(_wfs().WFSFormatError, match="misaligned"):
        _wfs().parse_lightning(payload.encode(), (60, 25))


def test_lightning_corrupt_values_are_skipped():
    payload = _fixture("wfs_lightning.xml").decode().replace(
        "60.27 24.94", "NaN 24.94"
    )
    assert len(_wfs().parse_lightning(payload.encode(), (60, 25))) == 2


def test_lightning_parser_deadline_is_seconds_not_milliseconds():
    with pytest.raises(TimeoutError, match="deadline"):
        _wfs().parse_lightning(
            _fixture("wfs_lightning.xml"), (60.17, 24.94),
            deadline=19.9, monotonic=lambda: 20.0
        )


@pytest.mark.parametrize(
    "fixture_name", ["wfs_lightning.xml", "wfs_sea_level.xml"]
)
def test_wfs_fixtures_contain_expected_feature_collection(fixture_name):
    from xml.etree import ElementTree

    document = ElementTree.fromstring(_fixture(fixture_name))
    assert document.tag.endswith("FeatureCollection")


def test_sea_level_uses_xml_element_names_and_ignores_n2000():
    rows = _wfs().parse_sea_level(_fixture("wfs_sea_level.xml"))
    assert rows == [
        ("2026-10-22T12:00:00+00:00", -4.75),
        ("2026-10-22T12:30:00+00:00", 23.5),
    ]


def test_sea_level_empty_data_is_not_last_successful_snapshot():
    payload = b'<FeatureCollection xmlns="http://www.opengis.net/wfs/2.0"/>'
    assert _wfs().parse_sea_level(payload) == []


def test_sea_level_bad_record_does_not_poison_valid_records():
    payload = _fixture("wfs_sea_level.xml").decode().replace(
        "<fmi:ParameterValue>-4.75</fmi:ParameterValue>",
        "<fmi:ParameterValue>invalid</fmi:ParameterValue>",
    )
    assert len(_wfs().parse_sea_level(payload.encode())) == 1


@pytest.mark.parametrize("parser", ["parse_lightning", "parse_sea_level"])
def test_error_xml_with_http_200_is_treated_as_failure(parser):
    wfs = _wfs()
    with pytest.raises(wfs.WFSFormatError, match="failed to convert"):
        if parser == "parse_lightning":
            wfs.parse_lightning(_fixture("wfs_exception.xml"), (60, 25))
        else:
            wfs.parse_sea_level(_fixture("wfs_exception.xml"))


def test_invalid_xml_and_oversized_payload_are_rejected():
    wfs = _wfs()
    with pytest.raises(wfs.WFSFormatError, match="invalid XML"):
        wfs.parse_sea_level(b"<broken>")
    with pytest.raises(wfs.WFSFormatError, match="exceeds"):
        wfs.parse_sea_level(b"x" * 8_000_001)


def test_reverse_geocoder_caches_and_throttles_without_waiting():
    wfs = _wfs()
    calls = []
    clock = [100.0]

    def resolve(latitude, longitude):
        calls.append((latitude, longitude))
        return SimpleNamespace(address="Helsinki")

    wfs.CachedReverseGeocoder._last_request = float("-inf")
    a = wfs.CachedReverseGeocoder(resolve, monotonic=lambda: clock[0])
    b = wfs.CachedReverseGeocoder(resolve, monotonic=lambda: clock[0])
    assert a.lookup(60.17, 24.94) == "Helsinki"
    assert a.lookup(60.1702, 24.9402) == "Helsinki"
    assert len(calls) == 1
    assert b.lookup(60.2, 25.0) is None
    assert len(calls) == 1
    clock[0] += 1.2
    assert b.lookup(60.2, 25.0) == "Helsinki"
    assert len(calls) == 2
    assert a.get_cached(60.17, 24.94) == "Helsinki"


def test_failed_reverse_geocoding_falls_back_without_caching_failure():
    wfs = _wfs()
    wfs.CachedReverseGeocoder._last_request = float("-inf")

    def fail(_latitude, _longitude):
        raise RuntimeError("external geocoder down")

    geocoder = wfs.CachedReverseGeocoder(fail, monotonic=lambda: 100.0)
    assert geocoder.lookup(61, 25) is None
    assert geocoder.get_cached(61, 25) is None


def test_geocoder_cache_is_bounded_to_256_entries():
    wfs = _wfs()
    clock = [100.0]
    geocoder = wfs.CachedReverseGeocoder(
        lambda latitude, longitude: SimpleNamespace(address="ok"),
        monotonic=lambda: clock[0],
    )
    wfs.CachedReverseGeocoder._last_request = float("-inf")
    for index in range(260):
        assert geocoder.lookup(60 + index / 1000, 25) == "ok"
        clock[0] += 1.2
    assert len(geocoder._cache) == 256
    assert geocoder.get_cached(60, 25) is None
    assert geocoder.get_cached(60.259, 25) == "ok"


def _model_classes():
    wfs = _wfs()
    namespace = {
        "datetime": datetime,
        "dt_util": SimpleNamespace(
            as_local=lambda stamp: stamp.astimezone(HELSINKI)
        ),
        "local_display_time": wfs.local_display_time,
    }
    return (
        source_definition("__init__.py", "FMILightningStruct", namespace=namespace),
        source_definition("__init__.py", "FMIMareoStruct", namespace=namespace),
    )


def test_models_preserve_public_local_clock_strings_for_utc_xml():
    Lightning, Mareo = _model_classes()
    strike = Lightning(
        "2026-10-22T12:00:00+00:00", "Helsinki", 1.254,
        2, -5.1, 0.3, 4.0
    )
    assert strike.time == "2026-10-22 15:00"
    assert strike.distance == pytest.approx(1.25)
    sea = Mareo()
    sea.append_values("2026-10-22T12:00:00+00:00", "12.5")
    assert sea.get_values()[0].time == "2026-10-22 15:00"


def test_best_time_rejects_tomorrow_across_year_boundary():
    from datetime import date

    const = SimpleNamespace(
        BEST_CONDITION_NOT_AVAIL="not_available",
        BEST_CONDITION_AVAIL="available",
        BEST_COND_SYMBOLS=[1],
    )
    dt_util = SimpleNamespace(
        now=lambda: datetime(2026, 12, 31, 12, tzinfo=UTC),
        as_local=lambda stamp: stamp.astimezone(UTC),
    )
    Coordinator = source_definition(
        "__init__.py", "FMIDataUpdateCoordinator",
        methods=["__update_best_weather_condition"],
        base="object",
        namespace={"dt_util": dt_util, "const": const, "date": date},
    )
    coordinator = Coordinator()
    weather_data = SimpleNamespace(
        time=datetime(2026, 12, 31, 11, tzinfo=UTC),
        temperature=SimpleNamespace(value=2),
        humidity=SimpleNamespace(value=50),
        wind_speed=SimpleNamespace(value=4),
        precipitation_amount=SimpleNamespace(value=0),
    )
    coordinator.get_weather = lambda: SimpleNamespace(data=weather_data)

    def forecast_day(timestamp, temperature):
        return SimpleNamespace(
            time=timestamp,
            symbol=SimpleNamespace(value=1),
            wind_speed=SimpleNamespace(value=4),
            temperature=SimpleNamespace(value=temperature),
            humidity=SimpleNamespace(value=50),
            precipitation_amount=SimpleNamespace(value=0),
        )

    coordinator.get_forecasts = lambda: [
        forecast_day(datetime(2026, 12, 31, 13, tzinfo=UTC), 10),
        forecast_day(datetime(2027, 1, 1, 1, tzinfo=UTC), 30),
    ]
    coordinator.min_wind_speed = 0
    coordinator.max_wind_speed = 15
    coordinator.min_temperature = -20
    coordinator.max_temperature = 35
    coordinator.min_humidity = 0
    coordinator.max_humidity = 100
    coordinator.min_precip = 0
    coordinator.max_precip = 10
    coordinator._FMIDataUpdateCoordinator__update_best_weather_condition()
    assert coordinator.best_state == "available"
    assert coordinator.best_temperature == 10
    assert coordinator.best_time.date() == date(2026, 12, 31)


def _coordinator_with_wfs_responses(*, http_error=False):
    """Extract actual coordinator request methods with fake HTTP/geopy."""
    import logging
    import time

    wfs = _wfs()
    Lightning, Mareo = _model_classes()
    requests = []
    address_queries = []

    def get(url, timeout):
        requests.append((url, timeout))

        def check():
            if http_error:
                raise RuntimeError("HTTP 502")

        return SimpleNamespace(
            content=(
                _fixture("wfs_lightning.xml") if "lightning" in url
                else _fixture("wfs_sea_level.xml")
            ),
            raise_for_status=check,
        )

    Coordinator = source_definition(
        "__init__.py",
        "FMIDataUpdateCoordinator",
        methods=[
            "__get_lightning_url",
            "__update_lightning_strikes",
            "__update_mareo_data",
        ],
        base="object",
        namespace={
            "requests": SimpleNamespace(get=get),
            "time": time,
            "timedelta": timedelta,
            "utc_time_parameter": lambda lookback=None: (
                "starttime=2026-10-21T12:00:00Z"
                if lookback else "starttime=2026-10-22T12:00:00Z"
            ),
            "utils": SimpleNamespace(
                get_bounding_box=lambda *a, **kw: SimpleNamespace(
                    lon_min=24, lon_max=26, lat_min=60, lat_max=62
                )
            ),
            "const": SimpleNamespace(
                LIGHTNING_DAYS_LIMIT=1,
                LIGHTNING_LIMIT=5,
                LIGHTNING_LOOP_TIMEOUT_IN_SECS=20,
                LIGHTNING_GET_URL="https://fmi.invalid/?lightning&",
                MAREO_GET_URL="https://fmi.invalid/?mareo&",
                TIMEOUT_LIGHTNING_PULL_IN_SECS=5,
                TIMEOUT_MAREO_PULL_IN_SECS=5,
            ),
            "parse_lightning": wfs.parse_lightning,
            "parse_sea_level": wfs.parse_sea_level,
            "FMILightningStruct": Lightning,
            "FMIMareoStruct": Mareo,
        },
    )
    coordinator = Coordinator()
    coordinator.latitude = 60.17
    coordinator.longitude = 24.94
    coordinator.lightning_radius = 200
    coordinator.logger = logging.getLogger("test.fmi.wfs")
    # Each simulated poll is at least two seconds after the previous one.
    clock = iter(range(100, 10000, 2))
    coordinator._reverse_geocoder = wfs.CachedReverseGeocoder(
        lambda latitude, longitude: (
            address_queries.append((latitude, longitude))
            or SimpleNamespace(address="Near Helsinki")
        ),
        monotonic=lambda: next(clock),
    )
    wfs.CachedReverseGeocoder._last_request = float("-inf")
    return coordinator, requests, address_queries


def test_coordinator_uses_utc_parameters_and_http_status_for_both_sources():
    coordinator, urls, _ = _coordinator_with_wfs_responses()
    lightning = coordinator._FMIDataUpdateCoordinator__update_lightning_strikes()
    mareo = coordinator._FMIDataUpdateCoordinator__update_mareo_data()
    assert len(lightning) == 3
    assert lightning[0].time == "2026-10-22 15:10"
    assert mareo.get_values()[0].sea_level == -4.75
    assert mareo.get_values()[0].time == "2026-10-22 15:00"
    assert "starttime=2026-10-21T12:00:00Z" in urls[0][0]
    assert "bbox=24,60,26,62" in urls[0][0]
    assert "starttime=2026-10-22T12:00:00Z" in urls[1][0]
    assert "latlon=60.17,24.94" in urls[1][0]
    assert [request[1] for request in urls] == [5, 5]


def test_coordinator_geocodes_no_more_than_one_uncached_strike_per_poll():
    coordinator, _urls, addresses = _coordinator_with_wfs_responses()
    first = coordinator._FMIDataUpdateCoordinator__update_lightning_strikes()
    assert len(addresses) == 1
    assert first[0].location == "Near Helsinki"
    assert first[1].location != "Near Helsinki"
    second = coordinator._FMIDataUpdateCoordinator__update_lightning_strikes()
    assert len(addresses) == 2
    assert second[0].location == "Near Helsinki"
    assert second[1].location == "Near Helsinki"


def test_coordinator_http_error_is_not_parsed_as_success():
    coordinator, _urls, _ = _coordinator_with_wfs_responses(http_error=True)
    with pytest.raises(RuntimeError, match="HTTP 502"):
        coordinator._FMIDataUpdateCoordinator__update_lightning_strikes()
    with pytest.raises(RuntimeError, match="HTTP 502"):
        coordinator._FMIDataUpdateCoordinator__update_mareo_data()
