"""Fault-tolerant parsing and request timestamps for FMI WFS XML.

No Home Assistant imports: XML behavior can be verified offline.
"""

import math
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone


class WFSFormatError(ValueError):
    """An FMI WFS response is incomplete, malformed or an error document."""


def utc_time_parameter(when=None, *, lookback=None):
    """Produce a real UTC WFS starttime parameter, independent of host TZ."""
    if when is None:
        when = datetime.now(timezone.utc)
    if when.tzinfo is None or when.utcoffset() is None:
        raise ValueError("FMI WFS timestamps must be timezone aware")
    when = when.astimezone(timezone.utc)
    if lookback is not None:
        when -= lookback
    return when.strftime("starttime=%Y-%m-%dT%H:%M:%SZ")


def local_display_time(value, localize):
    """Keep public YYYY-MM-DD HH:MM output while respecting HA timezone."""
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is not None and stamp.utcoffset() is not None:
        stamp = localize(stamp)
    return stamp.strftime("%Y-%m-%d %H:%M")


def _tag(element):
    """Extract XML local name regardless of namespace prefix."""
    return element.tag.rsplit("}", 1)[-1]


def _root(payload):
    """Validate the FMI response, including WFS exceptions returned as HTTP 200."""
    if len(payload) > 8_000_000:
        raise WFSFormatError("FMI WFS XML response exceeds 8 MB")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as error:
        raise WFSFormatError("FMI WFS returned invalid XML") from error
    if _tag(root) == "ExceptionReport":
        descriptions = [
            (element.text or "").strip()
            for element in root.iter()
            if _tag(element) == "ExceptionText" and element.text
        ]
        raise WFSFormatError(
            "FMI WFS exception: " + "; ".join(descriptions)[:250]
        )
    if _tag(root) != "FeatureCollection":
        raise WFSFormatError("FMI WFS did not return a FeatureCollection")
    return root


def _rows(value, width):
    """Split whitespace-separated GML rows independent of line breaks."""
    if not value or not value.strip():
        return []
    columns = value.split()
    if len(columns) % width:
        raise WFSFormatError("FMI WFS coverage contains an incomplete record")
    return [columns[offset:offset + width]
            for offset in range(0, len(columns), width)]


def _distance_km(lat, lon, origin):
    """Great-circle distance avoids geocoding or network calls for each strike."""
    lat1, lon1 = map(math.radians, origin)
    lat2, lon2 = math.radians(lat), math.radians(lon)
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    arc = (math.sin(delta_lat / 2)**2
           + math.cos(lat1) * math.cos(lat2)
           * math.sin(delta_lon / 2)**2)
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(arc)))


def _strike_record(location, metrics, origin):
    """Decode a positional FMI lightning row, discarding malformed values."""
    try:
        lat, lon, epoch = map(float, location)
        strikes, peak, cover, major = map(float, metrics)
        if not all(math.isfinite(v) for v in (
                lat, lon, epoch, strikes, peak, cover, major)):
            return None
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            return None
        if strikes < 0 or not strikes.is_integer():
            return None
        instant = datetime.fromtimestamp(epoch, timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
    return {
        "latitude": lat,
        "longitude": lon,
        "time": instant,
        "distance": _distance_km(lat, lon, origin),
        "strikes": int(strikes),
        "peak_current": peak,
        "cloud_cover": cover,
        "ellipse_major": major,
    }


def parse_lightning(payload, origin, *, limit=5, deadline=None,
                    monotonic=time.monotonic):
    """Return closest FMI strike rows, ordered newest first.

    Positions are triples latitude/longitude/Unix seconds. The matching
    doubleOrNilReasonTupleList has four fields: strikes, peak current,
    cloud cover and ellipse major. Mismatched coverage cannot be trusted.
    """
    root = _root(payload)
    positions = [
        _rows(element.text, 3)
        for element in root.iter() if _tag(element) == "positions"
    ]
    tuples = [
        _rows(element.text, 4)
        for element in root.iter()
        if _tag(element) == "doubleOrNilReasonTupleList"
    ]
    if not positions and not tuples:
        return []
    if len(positions) != len(tuples):
        raise WFSFormatError("FMI lightning coverage and values do not match")
    rows = []
    for points, values in zip(positions, tuples):
        if len(points) != len(values):
            raise WFSFormatError("FMI lightning positions and values are misaligned")
        for location, metrics in zip(points, values):
            if deadline is not None and monotonic() >= deadline:
                raise TimeoutError("FMI lightning parsing exceeded its deadline")
            row = _strike_record(location, metrics, origin)
            if row is not None:
                rows.append(row)
    closest = sorted(rows, key=lambda row: row["distance"])[:max(0, limit)]
    return sorted(closest, key=lambda row: row["time"], reverse=True)


def parse_sea_level(payload):
    """Parse FMI simple WFS SeaLevel records by XML names, never child index.

    SeaLevelN2000 is intentionally excluded as in the legacy integration.
    Return timezone-aware ISO timestamps paired with finite centimetre values.
    """
    root = _root(payload)
    result = {}
    for member in root.iter():
        if _tag(member) != "BsWfsElement":
            continue
        fields = {
            _tag(child): (child.text or "").strip()
            for child in member.iter() if child is not member
        }
        if fields.get("ParameterName") != "SeaLevel":
            continue
        try:
            time_text = fields["Time"]
            raw_value = fields["ParameterValue"]
            stamp = datetime.fromisoformat(time_text.replace("Z", "+00:00"))
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            value = float(raw_value)
            if not math.isfinite(value):
                continue
        except (KeyError, ValueError, OverflowError):
            continue
        result[stamp.astimezone(timezone.utc)] = value
    return [(stamp.isoformat(), result[stamp]) for stamp in sorted(result)]


class CachedReverseGeocoder:
    """One external lookup per 1.1 seconds across all FMI instances.

    Addresses are optional and cached by ~100 m cells, with a fixed bound on
    memory. When throttled or unavailable, callers use coordinates instead.
    """

    _rate_lock = threading.Lock()
    _last_request = float("-inf")

    def __init__(self, resolver, *, monotonic=time.monotonic):
        self._resolver = resolver
        self._monotonic = monotonic
        self._cache = {}

    def get_cached(self, latitude, longitude):
        """Return a known address without touching the network or limiter."""
        return self._cache.get((round(latitude, 3), round(longitude, 3)))

    def lookup(self, latitude, longitude):
        """Return cached/resolved address or None without blocking for a permit."""
        key = (round(latitude, 3), round(longitude, 3))
        if key in self._cache:
            return self._cache[key]
        with self._rate_lock:
            current = self._monotonic()
            if current - CachedReverseGeocoder._last_request < 1.1:
                return None
            CachedReverseGeocoder._last_request = current

        try:
            result = self._resolver(latitude, longitude)
            address = getattr(result, "address", None)
        # Reverse geocoding is optional: any provider failure falls back to GPS.
        # pylint: disable-next=broad-exception-caught
        except Exception:  # noqa: BLE001
            return None
        if not address:
            return None
        if len(self._cache) >= 256:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = address
        return address
