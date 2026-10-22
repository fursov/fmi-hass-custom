"""Normalize and aggregate FMI forecast slots into Home Assistant native forecasts.

This module intentionally has no Home Assistant imports so transformations can
be tested with representative FMI client data without loading HA.
"""

from collections import defaultdict
from datetime import UTC, datetime
from math import isfinite


def _value(point, field):
    """Get a finite FMI numeric value, preserving a real zero."""
    wrapped = getattr(point, field, None)
    value = getattr(wrapped, "value", None)
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        return None
    return value if isfinite(value) else None


def _condition(point, get_condition):
    """Translate an optional FMI symbol to the HA condition identifier."""
    symbol = getattr(getattr(point, "symbol", None), "value", None)
    return get_condition(symbol) if symbol is not None else None


def _valid_slots(points, now):
    """Return unique future timestamps in chronological order."""
    by_timestamp = {}
    for point in points or ():
        timestamp = getattr(point, "time", None)
        if not isinstance(timestamp, datetime):
            continue
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            continue
        if timestamp.astimezone(UTC) <= now:
            continue
        # If the source repeats a timestamp, use the final observation.
        by_timestamp[timestamp.astimezone(UTC)] = point
    return [by_timestamp[key] for key in sorted(by_timestamp)]


def _hourly(slot, local_time, get_condition):
    """One actual FMI slot; no interpolation of missing hours."""
    return {
        "datetime": local_time.isoformat(),
        "condition": _condition(slot, get_condition),
        "native_temperature": _value(slot, "temperature"),
        "native_precipitation": _value(slot, "precipitation_amount"),
        "native_wind_speed": _value(slot, "wind_speed"),
        "native_wind_gust_speed": _value(slot, "wind_gust"),
        "wind_bearing": _value(slot, "wind_direction"),
        "native_pressure": _value(slot, "pressure"),
        "humidity": _value(slot, "humidity"),
        "cloud_coverage": _value(slot, "cloud_cover"),
        "native_dew_point": _value(slot, "dew_point"),
    }


def _nearest_midday(entries):
    """Choose the representative point nearest local noon (stable on ties)."""
    return min(
        entries,
        key=lambda pair: abs(
            (pair[1] - pair[1].replace(
                hour=12, minute=0, second=0, microsecond=0
            )).total_seconds()
        ),
    )



def _daily(entries, get_condition, hourly_precipitation):
    """Aggregate one local-calendar-day group."""
    temperatures = [
        _value(slot, "temperature") for slot, _ in entries
    ]
    temperatures = [temp for temp in temperatures if temp is not None]
    sample, local_time = _nearest_midday(entries)
    summary = _hourly(sample, local_time, get_condition)

    precipitation = None
    if hourly_precipitation:
        amounts = [
            _value(slot, "precipitation_amount") for slot, _ in entries
        ]
        amounts = [amount for amount in amounts if amount is not None]
        if amounts:
            precipitation = sum(amounts)

    midnight = local_time.replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    summary.update({
        "datetime": midnight.isoformat(),
        "native_temperature": max(temperatures) if temperatures else None,
        "native_templow": min(temperatures) if temperatures else None,
        "native_precipitation": precipitation,
    })
    return summary


def build_forecast(
    points,
    *,
    daily,
    to_local,
    get_condition,
    hourly_precipitation=True,
    now=None,
):
    """Build an hourly or local-calendar-day forecast from FMI weather slots.

    FMI precipitation_amount is an *hourly accumulation* (mm), not a per-slot
    accumulation. Daily precipitation is therefore only summed when the query
    has one-hour cadence. For longer time steps we return None rather than
    present a misleading partial amount as the day's total.

    A day with incomplete hourly data contains the sum of *available* hourly
    amounts; it must not be treated as a guaranteed complete 24-hour total.
    """
    if now is None:
        now = datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    now = now.astimezone(UTC)

    slots = _valid_slots(points, now)
    if not daily:
        return [
            _hourly(slot, to_local(slot.time), get_condition)
            for slot in slots
        ]

    groups = defaultdict(list)
    for slot in slots:
        local_time = to_local(slot.time)
        groups[local_time.date()].append((slot, local_time))

    return [
        _daily(entries, get_condition, hourly_precipitation)
        for entries in groups.values()
    ]
