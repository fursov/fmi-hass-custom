"""Stable value/serialization behavior of the current small data structures."""

from datetime import datetime
from xml.etree import ElementTree

import pytest
from conftest import ROOT, source_definition


def test_sea_level_model_preserves_order_and_converts_numeric_values():
    Mareo = source_definition(
        "__init__.py", "FMIMareoStruct", namespace={"datetime": datetime}
    )
    record = Mareo()
    record.append_values("2026-01-01T00:00:00", "12.5")
    record.append_values("2026-01-01T00:30:00", "13")
    assert record.size() == 2
    assert [item.sea_level for item in record.get_values()] == [12.5, 13.0]
    assert record.get_values()[0].time == "2026-01-01 00:00"


def test_lightning_model_preserves_public_attributes():
    Lightning = source_definition(
        "__init__.py", "FMILightningStruct", namespace={"datetime": datetime}
    )
    strike = Lightning("2026-01-01 12:34:00", "Helsinki", 1.235, 2, 3.2, 0.1, 5.1)
    assert strike.location == "Helsinki"
    assert strike.time == "2026-01-01 12:34"
    assert strike.distance == pytest.approx(1.24)
    assert strike.strikes == 2
    assert strike.peak_current == pytest.approx(3.2)


def test_failure_fixture_is_valid_wfs_exception_xml():
    """Reserved for HTTP-error coordinator tests in PR2/PR3."""
    body = (ROOT / "tests/fixtures/wfs_exception.xml").read_bytes()
    exception = ElementTree.fromstring(body)
    assert exception.tag.endswith("ExceptionReport")
    message = exception.find(".//{http://www.opengis.net/ows/1.1}ExceptionText")
    assert message is not None
    assert "failed to convert" in message.text
