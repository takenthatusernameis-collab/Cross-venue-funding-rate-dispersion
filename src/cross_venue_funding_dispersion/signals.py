"""Causal funding normalization, time-weighted dispersion, and threshold helpers."""
from __future__ import annotations
from datetime import date, datetime, time, timedelta, timezone
import math
from statistics import pstdev
from typing import Any


def _utc(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _finite(value: Any, name: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def normalize_funding_rate(rate: float, interval_hours: float) -> float:
    """Linear 8-hour normalization; preserves the original event rate separately."""
    value = _finite(rate, "rate")
    interval = _finite(interval_hours, "interval_hours")
    if interval <= 0:
        raise ValueError("interval_hours must be positive")
    return value * 8.0 / interval


def time_weighted_mean(
    observations: list[dict[str, Any]],
    start: str | datetime,
    end: str | datetime,
    *,
    max_staleness_hours: float,
) -> float | None:
    """Mean of a piecewise-constant rate series; return None if coverage has a gap.

    Each observation has timestamp and rate_8h. A value is usable from its
    timestamp until the next observation, but never beyond max_staleness_hours.
    The first observation must cover the window start.
    """
    begin, finish = _utc(start), _utc(end)
    stale_limit = _finite(max_staleness_hours, "max_staleness_hours")
    if finish <= begin or stale_limit <= 0:
        raise ValueError("end must follow start and max_staleness_hours must be positive")
    rows = sorted((_utc(row["timestamp"]), _finite(row["rate_8h"], "rate_8h")) for row in observations)
    if not rows or rows[0][0] > begin:
        return None
    if len({timestamp for timestamp, _ in rows}) != len(rows):
        raise ValueError("duplicate observation timestamps are ambiguous")
    active = [row for row in rows if row[0] <= begin]
    if not active:
        return None
    current_time, current_rate = active[-1]
    if (begin - current_time).total_seconds() > stale_limit * 3600:
        return None
    future = [(ts, value) for ts, value in rows if begin < ts < finish]
    boundaries = future + [(finish, current_rate)]
    cursor = begin
    area = 0.0
    for next_time, _ in boundaries:
        if (next_time - current_time).total_seconds() > stale_limit * 3600:
            return None
        hours = (next_time - cursor).total_seconds() / 3600.0
        area += current_rate * hours
        cursor = next_time
        matches = [row for row in future if row[0] == next_time]
        if matches:
            current_time, current_rate = matches[0]
    if cursor < finish:
        if (finish - current_time).total_seconds() > stale_limit * 3600:
            return None
        area += current_rate * (finish - cursor).total_seconds() / 3600.0
    return area / ((finish - begin).total_seconds() / 3600.0)


def dispersion_from_venue_histories(
    histories: dict[str, list[dict[str, Any]]],
    start: str | datetime,
    end: str | datetime,
    *,
    minimum_venues: int,
    max_staleness_hours: float,
) -> tuple[float | None, dict[str, float]]:
    """Return population standard deviation and per-venue time-weighted means."""
    if minimum_venues < 2:
        raise ValueError("minimum_venues must be at least two")
    means = {}
    for venue, observations in sorted(histories.items()):
        mean = time_weighted_mean(observations, start, end, max_staleness_hours=max_staleness_hours)
        if mean is not None:
            means[venue] = mean
    if len(means) < minimum_venues:
        return None, means
    return pstdev(means.values()), means


def linear_quantile(values: list[float], percentile: float, *, minimum_observations: int = 1) -> float | None:
    """Type-7/linear quantile; insufficient samples yield None, never a fallback."""
    q = _finite(percentile, "percentile") / 100.0
    if not 0 <= q <= 1:
        raise ValueError("percentile must be in [0, 100]")
    if minimum_observations < 1:
        raise ValueError("minimum_observations must be positive")
    clean = sorted(_finite(value, "quantile value") for value in values)
    if len(clean) < minimum_observations:
        return None
    if not clean:
        return None
    position = (len(clean) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return clean[lower]
    return clean[lower] + (clean[upper] - clean[lower]) * (position - lower)


def prior_daily_threshold(
    samples: list[dict[str, Any]],
    signal_date: str | date,
    percentile: float,
    *,
    lookback_days: int = 90,
    minimum_observations: int = 30,
) -> float | None:
    """Select one latest <=23:00 UTC sample per prior date; exclude current date."""
    current = date.fromisoformat(signal_date) if isinstance(signal_date, str) else signal_date
    if lookback_days < 1 or minimum_observations < 1:
        raise ValueError("lookback_days and minimum_observations must be positive")
    lower_date = current - timedelta(days=lookback_days)
    latest: dict[date, tuple[time, float]] = {}
    cutoff = time(23, 0)
    for sample in samples:
        try:
            sample_date = date.fromisoformat(str(sample["date"]))
            snapshot = time.fromisoformat(str(sample["snapshot_time_utc"]))
            value = _finite(sample["dispersion"], "dispersion")
        except (KeyError, TypeError, ValueError):
            continue
        if not lower_date <= sample_date < current or snapshot > cutoff:
            continue
        prior = latest.get(sample_date)
        if prior is None or snapshot > prior[0]:
            latest[sample_date] = (snapshot, value)
    return linear_quantile([value for _, value in latest.values()], percentile, minimum_observations=minimum_observations)


def select_top_dispersion(
    values: dict[str, float],
    threshold: float | None,
    tail_fraction: float,
) -> list[str]:
    """Return stable asset IDs for the highest-dispersion eligible tail."""
    fraction = _finite(tail_fraction, "tail_fraction")
    if not 0 < fraction <= 1:
        raise ValueError("tail_fraction must be in (0, 1]")
    if threshold is None:
        return []
    cutoff = _finite(threshold, "threshold")
    eligible = [(asset, _finite(value, "dispersion")) for asset, value in values.items() if float(value) >= cutoff]
    eligible.sort(key=lambda pair: (-pair[1], pair[0]))
    if not eligible:
        return []
    count = max(1, math.ceil(len(eligible) * fraction))
    return [asset for asset, _ in eligible[:count]]
