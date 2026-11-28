#!/usr/bin/env python3
"""Source-reproducibility check for the persisted FVD053 candle series digests.

Closes the audited limitation "series content is bound by a recorded SHA-256
digest over (time, open, close) that cannot be re-derived without refetching the
raw venue data": this script refetches the same bounded free public candle
windows and recomputes every digest with an independent canonicalisation
implementation, then compares it to the value recorded in the target artifact.

Coverage-only. No signal, outcome, backtest, or performance metric is computed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path
from statistics import pstdev

sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_fvd053_anchor import (  # noqa: E402  (data retrieval only, not digesting)
    OKX_INST_ID,
    fetch_hl_candles,
    fetch_hl_funding,
    fetch_okx_candles,
    fetch_okx_funding,
    utc_ms,
)


def canonical_digest(rows: list[dict]) -> dict:
    """Independent implementation of the recorded candle-series digest.

    Canonical payload is the time-sorted list of ``{time, open, close}`` objects
    serialised with sorted keys and no whitespace; the digest is its SHA-256.
    """
    ordered = sorted(rows, key=lambda row: int(row["time"]))
    payload = json.dumps(
        [{"close": r.get("close"), "open": r.get("open"), "time": r.get("time")} for r in ordered],
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return {
        "row_count": len(ordered),
        "first_time_utc": _iso(ordered[0]["time"]) if ordered else None,
        "last_time_utc": _iso(ordered[-1]["time"]) if ordered else None,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _window(rows: list[dict]) -> dict:
    times = [int(r["time"]) for r in rows if "time" in r]
    if not times:
        return {"first_time_utc": None, "last_time_utc": None}
    return {"first_time_utc": _iso(min(times)), "last_time_utc": _iso(max(times))}


def _candle_index(rows: list[dict]) -> dict[str, dict]:
    """Map ISO open-time -> candle row so evidence timestamps resolve exactly."""
    return {_iso(row["time"]): row for row in rows if "time" in row}


def _funding_index(rows: list[dict]) -> dict[str, float]:
    """Map ISO settlement-time -> original funding rate from a refetched series."""
    return {_iso(row["time"]): float(row["rate"]) for row in rows if "time" in row}


def _to_ms(timestamp_utc: str | None) -> int | None:
    if not timestamp_utc:
        return None
    try:
        return int(datetime.fromisoformat(timestamp_utc.replace("Z", "+00:00")).timestamp() * 1000 + 0.5)
    except ValueError:
        return None


def funding_settlement_checks(
    signals: list[dict],
    funding_by_venue: dict[tuple[str, str], list[dict]],
    retention_truncated: dict[tuple[str, str], bool] | None = None,
) -> dict:
    """Compare every recorded settlement cash-flow input against refetched funding rows.

    Each ``funding_evidence`` row stores the venue, side, settlement timestamp, the
    original venue rate, the documented settlement interval, the 8h-normalized rate
    and the cash flow. A row passes only when the refetched funding series still
    serves that exact settlement timestamp with an identical rate (tolerance 0) and
    the recorded normalization/cash-flow arithmetic reproduces exactly.

    A settlement older than the venue's refetched history is labelled
    ``outside_retention`` (a documented vendor retention limit, not a failure) only
    when the fetch itself proves the venue truncated the series. Any other missing
    timestamp is a failure and is never silently skipped.
    """
    retention_truncated = retention_truncated or {}
    index = {key: _funding_index(rows) for key, rows in funding_by_venue.items()}
    windows: dict[tuple[str, str], tuple[int | None, int | None]] = {}
    for key, rows in funding_by_venue.items():
        times = [int(r["time"]) for r in rows if "time" in r]
        windows[key] = (min(times), max(times)) if times else (None, None)

    expected_interval = {"Hyperliquid": 1.0, "OKX": 8.0}
    rows_out: list[dict] = []
    for signal_index, signal in enumerate(signals):
        underlying = signal.get("underlying")
        for evidence in signal.get("funding_evidence") or []:
            venue = evidence.get("venue")
            timestamp = evidence.get("settlement_time_utc")
            rate = evidence.get("original_rate")
            interval = evidence.get("interval_hours")
            notional = evidence.get("notional")
            side = evidence.get("side")
            cash_flow = evidence.get("cash_flow")
            rate_8h = evidence.get("rate_8h")

            refetched_rate = (index.get((underlying, venue)) or {}).get(timestamp)
            interval_expected = expected_interval.get(venue)
            interval_ok = (
                interval_expected is None
                or (isinstance(interval, (int, float)) and float(interval) == interval_expected)
            )
            arithmetic_ok = True
            cash_expected = rate_8h_expected = None
            if isinstance(rate, (int, float)) and isinstance(interval, (int, float)) and interval > 0:
                rate_8h_expected = rate * 8.0 / interval
            if (isinstance(rate, (int, float)) and isinstance(notional, (int, float))
                    and side in (-1, 1)):
                cash_expected = -side * notional * rate
            if cash_expected is not None and cash_expected != cash_flow:
                arithmetic_ok = False
            if rate_8h_expected is not None and rate_8h_expected != rate_8h:
                arithmetic_ok = False

            row = {
                "signal_index": signal_index,
                "underlying": underlying,
                "venue": venue,
                "side": side,
                "settlement_time_utc": timestamp,
                "recorded_rate": rate,
                "refetched_rate": refetched_rate,
                "recorded_interval_hours": interval,
                "recorded_cash_flow": cash_flow,
                "recomputed_cash_flow": cash_expected,
                "interval_matches_venue": interval_ok,
                "arithmetic_reproduces": arithmetic_ok,
                "found": refetched_rate is not None,
            }
            if refetched_rate is None:
                start, _ = windows.get((underlying, venue), (None, None))
                ms = _to_ms(timestamp)
                outside = (
                    ms is not None
                    and start is not None
                    and ms < start
                    and bool(retention_truncated.get((underlying, venue)))
                )
                row["status"] = "outside_retention" if outside else "not_found"
                row["passed"] = outside and arithmetic_ok and interval_ok
            else:
                rate_ok = float(refetched_rate) == float(rate)
                row["rate_matches"] = rate_ok
                row["status"] = "matched" if (rate_ok and arithmetic_ok and interval_ok) else "mismatch"
                row["passed"] = row["status"] == "matched"
            rows_out.append(row)

    failed = [r for r in rows_out if not r["passed"]]
    return {
        "rows_expected": len(rows_out),
        "rows_matched": sum(1 for r in rows_out if r["status"] == "matched"),
        "rows_outside_retention": sum(1 for r in rows_out if r["status"] == "outside_retention"),
        "rows_not_found": sum(1 for r in rows_out if r["status"] == "not_found"),
        "rows_failed": len(failed),
        "recorded_cash_flow_total": sum(
            float(r["recorded_cash_flow"]) for r in rows_out
            if isinstance(r["recorded_cash_flow"], (int, float))
        ),
        "recomputed_cash_flow_total": sum(
            float(r["recomputed_cash_flow"]) for r in rows_out
            if isinstance(r["recomputed_cash_flow"], (int, float))
        ),
        "all_matched": not failed,
        "rows": rows_out,
    }


def execution_price_checks(signals: list[dict], candles_by_venue: dict[tuple[str, str], list[dict]]) -> dict:
    """Compare every recorded entry/exit candle against the refetched candle rows.

    ``candles_by_venue`` is keyed by ``(underlying, venue)``. Each signal carries
    its own ``underlying`` and four ``candle_evidence`` rows (long/short x
    entry/exit). A row passes only when the refetched candle at that exact
    timestamp has identical ``open`` and ``close`` values (tolerance 0).
    """
    index = {key: _candle_index(rows) for key, rows in candles_by_venue.items()}
    rows: list[dict] = []
    for signal_index, signal in enumerate(signals):
        underlying = signal.get("underlying")
        entry_time = signal.get("entry_time_utc")
        exit_time = signal.get("exit_time_utc")
        for evidence in signal.get("candle_evidence") or []:
            venue = evidence.get("venue")
            timestamp = evidence.get("timestamp_utc")
            role = "entry" if timestamp == entry_time else ("exit" if timestamp == exit_time else "unknown")
            candle = (index.get((underlying, venue)) or {}).get(timestamp)
            row = {
                "signal_index": signal_index,
                "underlying": underlying,
                "venue": venue,
                "side": evidence.get("side"),
                "role": role,
                "timestamp_utc": timestamp,
                "recorded_open": evidence.get("open"),
                "recorded_close": evidence.get("close"),
                "refetched_open": candle.get("open") if candle else None,
                "refetched_close": candle.get("close") if candle else None,
                "found": candle is not None,
            }
            row["passed"] = bool(
                candle is not None
                and row["refetched_open"] == row["recorded_open"]
                and row["refetched_close"] == row["recorded_close"]
            )
            rows.append(row)

    internal: list[dict] = []
    for signal_index, signal in enumerate(signals):
        entry_time = signal.get("entry_time_utc")
        exit_time = signal.get("exit_time_utc")
        long_venue = signal.get("long_venue")
        short_venue = signal.get("short_venue")
        for role, expected_time, price_key in (
            ("entry", entry_time, "entry_price_long"),
            ("exit", exit_time, "exit_price_long"),
        ):
            match = next(
                (e for e in (signal.get("candle_evidence") or [])
                 if e.get("venue") == long_venue and e.get("timestamp_utc") == expected_time),
                None,
            )
            internal.append({
                "signal_index": signal_index,
                "underlying": signal.get("underlying"),
                "venue": long_venue,
                "role": role,
                "timestamp_utc": expected_time,
                "recorded_signal_price": signal.get(price_key),
                "recorded_candle_open": match.get("open") if match else None,
                "passed": bool(match is not None and match.get("open") == signal.get(price_key)),
            })
            price_key = "entry_price_short" if role == "entry" else "exit_price_short"
            match = next(
                (e for e in (signal.get("candle_evidence") or [])
                 if e.get("venue") == short_venue and e.get("timestamp_utc") == expected_time),
                None,
            )
            internal.append({
                "signal_index": signal_index,
                "underlying": signal.get("underlying"),
                "venue": short_venue,
                "role": role,
                "timestamp_utc": expected_time,
                "recorded_signal_price": signal.get(price_key),
                "recorded_candle_open": match.get("open") if match else None,
                "passed": bool(match is not None and match.get("open") == signal.get(price_key)),
            })

    failed = [r for r in rows if not r["passed"]]
    internal_failed = [r for r in internal if not r["passed"]]
    return {
        "rows_expected": len(rows),
        "rows_matched": len(rows) - len(failed),
        "rows_failed": len(failed),
        "rows_not_found": sum(1 for r in failed if not r["found"]),
        "internal_price_checks": len(internal),
        "internal_price_failed": len(internal_failed),
        "all_matched": not failed and not internal_failed,
        "rows": rows,
        "internal_checks": internal,
    }


def _as_datetime(timestamp_utc: str) -> datetime:
    return datetime.fromisoformat(timestamp_utc.replace("Z", "+00:00"))


def _normalized_observations(
    rows: list[dict], interval_hours: float, start_ms: int, end_ms: int
) -> list[dict]:
    """Refetched funding rows inside [start_ms, end_ms] as 8h-normalized observations."""
    observations = []
    for row in rows:
        moment = int(row["time"])
        if start_ms <= moment <= end_ms:
            observations.append({
                "timestamp": _iso(moment),
                "rate_8h": float(row["rate"]) * 8.0 / interval_hours,
            })
    return observations


def time_weighted_mean(
    observations: list[dict], begin: datetime, end: datetime, *, max_staleness_hours: float
) -> float | None:
    """Independent piecewise-constant mean; ``None`` if the window is not covered.

    Mirrors the documented rule without importing the producer module: the first
    observation may not start after the window, a value is carried forward only up
    to ``max_staleness_hours``, and any coverage hole yields ``None`` (never a fill).
    """
    if end <= begin or max_staleness_hours <= 0:
        raise ValueError("end must follow begin and max_staleness_hours must be positive")
    rows = sorted((_as_datetime(o["timestamp"]), float(o["rate_8h"])) for o in observations)
    if not rows or rows[0][0] > begin:
        return None
    if len({timestamp for timestamp, _ in rows}) != len(rows):
        raise ValueError("duplicate observation timestamps are ambiguous")
    active = [row for row in rows if row[0] <= begin]
    if not active:
        return None
    current_time, current_rate = active[-1]
    if (begin - current_time).total_seconds() > max_staleness_hours * 3600:
        return None
    future = [(timestamp, value) for timestamp, value in rows if begin < timestamp < end]
    cursor = begin
    area = 0.0
    for next_time, _ in future + [(end, current_rate)]:
        if (next_time - current_time).total_seconds() > max_staleness_hours * 3600:
            return None
        hours = (next_time - cursor).total_seconds() / 3600.0
        area += current_rate * hours
        cursor = next_time
        matches = [row for row in future if row[0] == next_time]
        if matches:
            current_time, current_rate = matches[0]
    if cursor < end:
        if (end - current_time).total_seconds() > max_staleness_hours * 3600:
            return None
        area += current_rate * (end - cursor).total_seconds() / 3600.0
    return area / ((end - begin).total_seconds() / 3600.0)


def dispersion_from_venues(
    hl_observations: list[dict],
    okx_observations: list[dict],
    window_start: datetime,
    signal_time: datetime,
    *,
    max_staleness_hours: float,
) -> tuple[float | None, dict[str, float]]:
    """Population standard deviation of per-venue time-weighted means (>=2 venues)."""
    means: dict[str, float] = {}
    for venue, observations in (("Hyperliquid", hl_observations), ("OKX", okx_observations)):
        mean = time_weighted_mean(
            observations, window_start, signal_time, max_staleness_hours=max_staleness_hours
        )
        if mean is not None:
            means[venue] = mean
    if len(means) < 2:
        return None, means
    return pstdev(means.values()), means


def linear_quantile(values: list[float], percentile: float, *, minimum_observations: int = 1) -> float | None:
    """Type-7/linear quantile; insufficient samples yield ``None`` (never a fallback)."""
    q = float(percentile) / 100.0
    if not 0 <= q <= 1:
        raise ValueError("percentile must be in [0, 100]")
    if minimum_observations < 1:
        raise ValueError("minimum_observations must be positive")
    clean = sorted(float(value) for value in values)
    if len(clean) < minimum_observations or not clean:
        return None
    position = (len(clean) - 1) * q
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return clean[lower]
    return clean[lower] + (clean[upper] - clean[lower]) * (position - lower)


def prior_daily_threshold(
    samples: list[dict],
    signal_date: str,
    percentile: float,
    *,
    lookback_days: int,
    minimum_observations: int,
) -> float | None:
    """One latest <=23:00 UTC sample per prior date inside the lookback, current excluded."""
    current = date.fromisoformat(signal_date)
    lower_date = current - timedelta(days=lookback_days)
    cutoff = dt_time(23, 0)
    latest: dict[date, tuple[dt_time, float]] = {}
    for sample in samples:
        try:
            sample_date = date.fromisoformat(str(sample["date"]))
            snapshot = dt_time.fromisoformat(str(sample["snapshot_time_utc"]))
            value = float(sample["dispersion"])
        except (KeyError, TypeError, ValueError):
            continue
        if not lower_date <= sample_date < current or snapshot > cutoff:
            continue
        prior = latest.get(sample_date)
        if prior is None or snapshot > prior[0]:
            latest[sample_date] = (snapshot, value)
    return linear_quantile(
        [value for _, value in latest.values()], percentile, minimum_observations=minimum_observations
    )


def _retention_limited(
    underlying: str,
    rows: list[dict],
    ws_ms: int,
    retention_truncated: dict[tuple[str, str], bool],
) -> bool:
    """True only when a venue provably truncated history below the needed window start."""
    if not retention_truncated.get((underlying, "OKX")):
        return False
    okx_rows = rows if rows else []
    if not okx_rows:
        return True
    return min(int(row["time"]) for row in okx_rows) > ws_ms


def dispersion_threshold_checks(
    artifact: dict,
    funding_by_venue: dict[tuple[str, str], list[dict]],
    retention_truncated: dict[tuple[str, str], bool] | None = None,
) -> dict:
    """Recompute every daily cross-venue dispersion and prior-90-date 80th-percentile threshold.

    Dispersion is recomputed from refetched 1h Hyperliquid + 8h OKX funding rows with
    an independent time-weighted-mean/population-std implementation (tolerance 0).
    The threshold rule is re-derived from the persisted daily dispersion series (the
    artifact's own documented threshold inputs), including current-date exclusion and
    the no-fallback minimum-observation rule. Rows whose OKX funding window predates
    the current rolling retention are labelled ``outside_retention`` only when the
    refetch itself proves truncation; every other gap is a hard failure.
    """
    retention_truncated = retention_truncated or {}
    params = artifact.get("anchor_params") or {}
    lookback_hours = int(params.get("dispersion_lookback_hours", 24))
    percentile = float(params.get("entry_percentile", 80))
    threshold_days = int(params.get("threshold_lookback_days", 90))
    min_obs = int(params.get("threshold_minimum_observations", 30))
    tail_fraction = float(params.get("portfolio_tail_fraction", 0.1))
    staleness_hours = float(lookback_hours)
    window_start = _as_datetime(artifact["window_start_utc"])
    window_end = _as_datetime(artifact["window_end_utc"])

    evidence = artifact.get("dispersion_evidence") or []
    underlyings = artifact.get("underlyings") or sorted(
        {u for entry in evidence for u in (entry.get("underlyings") or {})}
    )

    dispersion_rows: list[dict] = []
    for entry in evidence:
        day_str = entry.get("date_utc")
        signal_time = datetime.fromisoformat(f"{day_str}T23:00:00+00:00")
        ws = signal_time - timedelta(hours=lookback_hours)
        ws_ms = int(ws.timestamp() * 1000)
        st_ms = int(signal_time.timestamp() * 1000)
        ext_ms = ws_ms - int(staleness_hours * 3600 * 1000)
        for underlying in underlyings:
            recorded = (entry.get("underlyings") or {}).get(underlying) or {}
            recorded_value = recorded.get("dispersion")
            hl_rows = funding_by_venue.get((underlying, "Hyperliquid")) or []
            okx_rows = funding_by_venue.get((underlying, "OKX")) or []
            hl_window = _normalized_observations(hl_rows, 1.0, ws_ms, st_ms)
            okx_window = _normalized_observations(okx_rows, 8.0, ws_ms, st_ms)
            recomputed = None
            means: dict[str, float] = {}
            if hl_window and okx_window:
                hl_ext = _normalized_observations(hl_rows, 1.0, ext_ms, st_ms)
                okx_ext = _normalized_observations(okx_rows, 8.0, ext_ms, st_ms)
                recomputed, means = dispersion_from_venues(
                    hl_ext, okx_ext, ws, signal_time, max_staleness_hours=staleness_hours
                )
            row = {
                "date_utc": day_str,
                "underlying": underlying,
                "recorded_dispersion": recorded_value,
                "recomputed_dispersion": recomputed,
                "recomputed_venue_means": means,
                "signal_time_utc": signal_time.isoformat().replace("+00:00", "Z"),
                "window_start_utc": ws.isoformat().replace("+00:00", "Z"),
            }
            if recorded_value is None and recomputed is None:
                row["status"] = "matched"
            elif recorded_value is not None and recomputed is not None:
                row["status"] = "matched" if float(recorded_value) == recomputed else "mismatch"
            elif recorded_value is not None and recomputed is None and _retention_limited(
                underlying, okx_rows, ws_ms, retention_truncated
            ):
                row["status"] = "outside_retention"
            else:
                row["status"] = "mismatch"
            row["passed"] = row["status"] in ("matched", "outside_retention")
            dispersion_rows.append(row)

    samples_by_underlying: dict[str, list[dict]] = {u: [] for u in underlyings}
    for entry in evidence:
        for underlying in underlyings:
            value = ((entry.get("underlyings") or {}).get(underlying) or {}).get("dispersion")
            if value is not None:
                samples_by_underlying[underlying].append({
                    "date": entry.get("date_utc"),
                    "snapshot_time_utc": "23:00:00",
                    "dispersion": value,
                })

    threshold_rows: list[dict] = []
    for entry in evidence:
        day_str = entry.get("date_utc")
        if not (window_start.date().isoformat() <= day_str <= window_end.date().isoformat()):
            continue
        for underlying in underlyings:
            recorded = (entry.get("underlyings") or {}).get(underlying) or {}
            recomputed = prior_daily_threshold(
                samples_by_underlying[underlying],
                day_str,
                percentile,
                lookback_days=threshold_days,
                minimum_observations=min_obs,
            )
            recorded_threshold = recorded.get("prior_threshold")
            eligibility_ok = bool(recorded.get("threshold_eligible")) == (recomputed is not None)
            threshold_rows.append({
                "date_utc": day_str,
                "underlying": underlying,
                "recorded_prior_threshold": recorded_threshold,
                "recomputed_prior_threshold": recomputed,
                "threshold_eligible_flag_matches": eligibility_ok,
                "passed": (recorded_threshold == recomputed) and eligibility_ok,
            })

    eligible_by_date: dict[str, list[tuple[str, float]]] = {}
    for entry in evidence:
        day_str = entry.get("date_utc")
        eligible = []
        for underlying in underlyings:
            recorded = (entry.get("underlyings") or {}).get(underlying) or {}
            dispersion = recorded.get("dispersion")
            threshold = prior_daily_threshold(
                samples_by_underlying[underlying],
                day_str,
                percentile,
                lookback_days=threshold_days,
                minimum_observations=min_obs,
            )
            if dispersion is not None and threshold is not None and float(dispersion) >= threshold:
                eligible.append((underlying, float(dispersion)))
        eligible.sort(key=lambda pair: (-pair[1], pair[0]))
        count = max(1, math.ceil(len(eligible) * tail_fraction)) if eligible else 0
        eligible_by_date[day_str] = eligible[:count]

    selection_rows: list[dict] = []
    for entry in evidence:
        day_str = entry.get("date_utc")
        expected = {name for name, _value in eligible_by_date.get(day_str, [])}
        recorded = {
            underlying for underlying in underlyings
            if ((entry.get("underlyings") or {}).get(underlying) or {}).get("selected")
        }
        selection_rows.append({
            "date_utc": day_str,
            "recorded_selected": sorted(recorded),
            "recomputed_selected": sorted(expected),
            "passed": recorded == expected,
        })

    dispersion_failed = [r for r in dispersion_rows if not r["passed"]]
    threshold_failed = [r for r in threshold_rows if not r["passed"]]
    selection_failed = [r for r in selection_rows if not r["passed"]]
    return {
        "dates_expected": len(evidence),
        "underlyings": underlyings,
        "dispersion_rows_expected": len(dispersion_rows),
        "dispersion_rows_matched": sum(1 for r in dispersion_rows if r["status"] == "matched"),
        "dispersion_rows_outside_retention": sum(
            1 for r in dispersion_rows if r["status"] == "outside_retention"
        ),
        "dispersion_rows_failed": len(dispersion_failed),
        "dispersion_matched_including_retention": sum(1 for r in dispersion_rows if r["passed"]),
        "threshold_rows_expected": len(threshold_rows),
        "threshold_rows_matched": sum(1 for r in threshold_rows if r["passed"]),
        "threshold_rows_failed": len(threshold_failed),
        "selection_rows_expected": len(selection_rows),
        "selection_rows_matched": sum(1 for r in selection_rows if r["passed"]),
        "selection_rows_failed": len(selection_failed),
        "all_matched": not dispersion_failed and not threshold_failed and not selection_failed,
        "dispersion_rows": dispersion_rows,
        "threshold_rows": threshold_rows,
        "selection_rows": selection_rows,
    }


def selection_observation_checks(
    artifact: dict,
    funding_by_venue: dict[tuple[str, str], list[dict]],
    retention_truncated: dict[tuple[str, str], bool] | None = None,
) -> dict:
    """Verify each selected signal window's recorded funding observations and dispersion.

    For every persisted ``selection_evidence`` underlying set: each recorded
    observation must exist in the refetched venue funding series with an identical
    original rate (tolerance 0) and reproducible 8h normalization; the window
    dispersion must reproduce exactly from those observations and equal the
    artifact's ``dispersion_evidence`` value for the same date.
    """
    retention_truncated = retention_truncated or {}
    params = artifact.get("anchor_params") or {}
    lookback_hours = int(params.get("dispersion_lookback_hours", 24))
    staleness_hours = float(lookback_hours)
    recorded_dispersion = {
        entry.get("date_utc"): entry.get("underlyings") or {}
        for entry in (artifact.get("dispersion_evidence") or [])
    }
    rate_index = {key: _funding_index(rows) for key, rows in funding_by_venue.items()}
    windows: dict[tuple[str, str], tuple[int | None, int | None]] = {}
    for key, rows in funding_by_venue.items():
        times = [int(r["time"]) for r in rows if "time" in r]
        windows[key] = (min(times), max(times)) if times else (None, None)

    rows_out: list[dict] = []
    dispersion_rows: list[dict] = []
    for entry_index, entry in enumerate(artifact.get("selection_evidence") or []):
        day_str = entry.get("date_utc")
        signal_time = _as_datetime(entry["signal_time_utc"])
        window_start = _as_datetime(entry["window_start_utc"])
        for underlying, payload in sorted((entry.get("underlyings") or {}).items()):
            for venue in ("Hyperliquid", "OKX"):
                observations = (payload.get("observations") or {}).get(venue) or []
                interval_expected = 1.0 if venue == "Hyperliquid" else 8.0
                for observation in observations:
                    timestamp = observation.get("timestamp")
                    original_rate = observation.get("original_rate")
                    interval = observation.get("interval_hours")
                    rate_8h = observation.get("rate_8h")
                    refetched_rate = (rate_index.get((underlying, venue)) or {}).get(timestamp)
                    arithmetic_ok = (
                        isinstance(original_rate, (int, float))
                        and isinstance(interval, (int, float))
                        and float(interval) == interval_expected
                        and rate_8h == original_rate * 8.0 / interval
                    )
                    row = {
                        "selection_index": entry_index,
                        "underlying": underlying,
                        "venue": venue,
                        "timestamp_utc": timestamp,
                        "recorded_original_rate": original_rate,
                        "refetched_rate": refetched_rate,
                        "arithmetic_reproduces": arithmetic_ok,
                    }
                    if refetched_rate is None:
                        start, _ = windows.get((underlying, venue), (None, None))
                        ms = _to_ms(timestamp)
                        outside = (
                            ms is not None and start is not None and ms < start
                            and bool(retention_truncated.get((underlying, venue)))
                        )
                        row["status"] = "outside_retention" if outside else "not_found"
                        row["passed"] = outside and arithmetic_ok
                    elif float(refetched_rate) == float(original_rate) and arithmetic_ok:
                        row["status"] = "matched"
                        row["passed"] = True
                    else:
                        row["status"] = "mismatch"
                        row["passed"] = False
                    rows_out.append(row)

            means: dict[str, float] = {}
            for venue in ("Hyperliquid", "OKX"):
                means[venue] = time_weighted_mean(
                    (payload.get("observations") or {}).get(venue) or [],
                    window_start,
                    signal_time,
                    max_staleness_hours=staleness_hours,
                )
            available = {v: m for v, m in means.items() if m is not None}
            recomputed = pstdev(available.values()) if len(available) >= 2 else None
            recorded = payload.get("dispersion")
            evidence_value = ((recorded_dispersion.get(day_str) or {}).get(underlying) or {}).get(
                "dispersion"
            )
            dispersion_rows.append({
                "selection_index": entry_index,
                "date_utc": day_str,
                "underlying": underlying,
                "recorded_dispersion": recorded,
                "recomputed_dispersion": recomputed,
                "dispersion_evidence_value": evidence_value,
                "matches_evidence_series": recorded == evidence_value,
                "passed": recomputed is not None and recorded == recomputed and recorded == evidence_value,
            })

    failed = [r for r in rows_out if not r["passed"]]
    dispersion_failed = [r for r in dispersion_rows if not r["passed"]]
    return {
        "observation_rows_expected": len(rows_out),
        "observation_rows_matched": sum(1 for r in rows_out if r["status"] == "matched"),
        "observation_rows_outside_retention": sum(
            1 for r in rows_out if r["status"] == "outside_retention"
        ),
        "observation_rows_not_found": sum(1 for r in rows_out if r["status"] == "not_found"),
        "observation_rows_failed": len(failed),
        "underlying_windows_expected": len(dispersion_rows),
        "underlying_windows_matched": sum(1 for r in dispersion_rows if r["passed"]),
        "underlying_windows_failed": len(dispersion_failed),
        "all_matched": not failed and not dispersion_failed,
        "rows": rows_out,
        "dispersion_rows": dispersion_rows,
    }


def verify(artifact_path: Path, output_path: Path, underlyings: list[str] | None = None) -> dict:
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    recorded = artifact.get("series_digests") or {}
    start_ms = utc_ms(artifact["window_start_utc"])
    end_ms = utc_ms(artifact["fetch_end_utc"])
    targets = underlyings or list(recorded)

    series: dict[str, dict] = {}
    candles_by_venue: dict[tuple[str, str], list[dict]] = {}
    funding_by_venue: dict[tuple[str, str], list[dict]] = {}
    retention_truncated: dict[tuple[str, str], bool] = {}
    for u in targets:
        hl_candles, hl_meta = fetch_hl_candles(u, start_ms, end_ms)
        hl_funding, hl_funding_meta = fetch_hl_funding(u, start_ms, end_ms)
        okx_candles, okx_meta = fetch_okx_candles(OKX_INST_ID[u], start_ms, end_ms)
        okx_funding, okx_funding_meta = fetch_okx_funding(OKX_INST_ID[u], start_ms, end_ms)
        candles_by_venue[(u, "Hyperliquid")] = hl_candles
        candles_by_venue[(u, "OKX")] = okx_candles
        funding_by_venue[(u, "Hyperliquid")] = hl_funding
        funding_by_venue[(u, "OKX")] = okx_funding
        retention_truncated[(u, "Hyperliquid")] = False
        retention_truncated[(u, "OKX")] = okx_funding_meta.get("stop_reason") == "page_not_full"

        per_venue = {}
        for venue, candles, funding, cmeta, fmeta in (
            ("Hyperliquid", hl_candles, hl_funding, hl_meta, hl_funding_meta),
            ("OKX", okx_candles, okx_funding, okx_meta, okx_funding_meta),
        ):
            recomputed = canonical_digest(candles)
            reference = (recorded.get(u) or {}).get(venue) or {}
            ref_candles = reference.get("candles") or {}
            per_venue[venue] = {
                "recorded": ref_candles,
                "recomputed": recomputed,
                "candle_digest_match": (
                    ref_candles.get("sha256") == recomputed["sha256"]
                    and ref_candles.get("row_count") == recomputed["row_count"]
                    and ref_candles.get("first_time_utc") == recomputed["first_time_utc"]
                    and ref_candles.get("last_time_utc") == recomputed["last_time_utc"]
                ),
                "recorded_funding_rows": reference.get("funding_rows"),
                "recomputed_funding_rows": len(funding),
                "funding_row_count_match": reference.get("funding_rows") == len(funding),
                "funding_window": _window(funding),
                "fetch": {
                    "candles": cmeta,
                    "funding": fmeta,
                },
            }
        series[u] = per_venue

    checks = []
    funding_observations = []
    for u, per_venue in series.items():
        for venue, record in per_venue.items():
            checks.append({
                "check": f"candle_digest:{u}:{venue}",
                "passed": record["candle_digest_match"],
                "detail": {"recorded_sha256": record["recorded"].get("sha256"),
                           "recomputed_sha256": record["recomputed"]["sha256"]},
            })
            funding_observations.append({
                "underlying": u,
                "venue": venue,
                "recorded_rows": record["recorded_funding_rows"],
                "recomputed_rows": record["recomputed_funding_rows"],
                "reproduced": record["funding_row_count_match"],
                "recomputed_earliest_utc": record["funding_window"]["first_time_utc"],
                "recomputed_latest_utc": record["funding_window"]["last_time_utc"],
            })

    failed = [c for c in checks if not c["passed"]]
    truncated = [o for o in funding_observations if not o["reproduced"]]
    execution = execution_price_checks(artifact.get("signals") or [], candles_by_venue)
    funding = funding_settlement_checks(
        artifact.get("signals") or [], funding_by_venue, retention_truncated
    )
    dispersion = dispersion_threshold_checks(artifact, funding_by_venue, retention_truncated)
    selection = selection_observation_checks(artifact, funding_by_venue, retention_truncated)
    verdict = (
        "PASS"
        if not failed
        and execution["all_matched"]
        and funding["all_matched"]
        and dispersion["all_matched"]
        and selection["all_matched"]
        else "FAIL"
    )
    return {
        "schema_version": "fvd053-series-digest-verification-v1",
        "run_type": "SOURCE_REPRODUCIBILITY_VERIFICATION",
        "target_artifact": str(artifact_path.name),
        "target_experiment_id": artifact.get("experiment_id"),
        "target_observed_at_utc": artifact.get("observed_at_utc"),
        "target_file_sha256": _file_sha256(artifact_path),
        "window_start_utc": artifact["window_start_utc"],
        "fetch_end_utc": artifact["fetch_end_utc"],
        "underlyings": targets,
        "series": series,
        "checks": checks,
        "funding_row_observations": funding_observations,
        "funding_row_counts_reproduced": not truncated,
        "funding_row_count_mismatches": len(truncated),
        "passed_checks": len(checks) - len(failed),
        "failed_checks": len(failed),
        "failed_check_names": [c["check"] for c in failed],
        "execution_price_provenance": execution,
        "execution_price_rows_matched": execution["rows_matched"],
        "execution_price_rows_expected": execution["rows_expected"],
        "execution_price_rows_failed": execution["rows_failed"],
        "funding_settlement_provenance": funding,
        "funding_settlement_rows_expected": funding["rows_expected"],
        "funding_settlement_rows_matched": funding["rows_matched"],
        "funding_settlement_rows_outside_retention": funding["rows_outside_retention"],
        "funding_settlement_rows_failed": funding["rows_failed"],
        "dispersion_threshold_provenance": dispersion,
        "dispersion_rows_expected": dispersion["dispersion_rows_expected"],
        "dispersion_rows_matched": dispersion["dispersion_rows_matched"],
        "dispersion_rows_outside_retention": dispersion["dispersion_rows_outside_retention"],
        "dispersion_rows_failed": dispersion["dispersion_rows_failed"],
        "threshold_rows_expected": dispersion["threshold_rows_expected"],
        "threshold_rows_matched": dispersion["threshold_rows_matched"],
        "threshold_rows_failed": dispersion["threshold_rows_failed"],
        "selection_rule_rows_expected": dispersion["selection_rows_expected"],
        "selection_rule_rows_matched": dispersion["selection_rows_matched"],
        "selection_rule_rows_failed": dispersion["selection_rows_failed"],
        "selection_observation_provenance": selection,
        "selection_observation_rows_expected": selection["observation_rows_expected"],
        "selection_observation_rows_matched": selection["observation_rows_matched"],
        "selection_observation_rows_outside_retention": selection["observation_rows_outside_retention"],
        "selection_observation_rows_failed": selection["observation_rows_failed"],
        "selection_window_dispersions_expected": selection["underlying_windows_expected"],
        "selection_window_dispersions_matched": selection["underlying_windows_matched"],
        "verdict": verdict,
        "backtest_completed": False,
        "performance_metrics_computed": False,
        "confirmatory_status_preserved": artifact.get("confirmatory_status_preserved"),
        "economic_claim": False,
        "limitations": [
            "Coverage/provenance verification only: no signal, outcome, or performance metric is computed.",
            "A matching digest proves the recorded candle series reproduces from the current public venue API bytes; "
            "it does not prove the venue never revised history.",
            "Execution-price checks compare recorded entry/exit candle open/close values to refetched rows with "
            "tolerance 0; they prove price provenance only, not that the trades were executable at those prices.",
            "Funding row counts are reported separately from the candle digests because OKX publishes a rolling "
            "~3-month funding history: rows older than the retention boundary cannot be refetched even though they "
            "remain persisted in the target artifact's settlement and selection evidence.",
            "Funding settlement checks compare each recorded venue/side/settlement-timestamp rate, interval, 8h "
            "normalization and cash flow against refetched rows with tolerance 0. Settlements older than a venue's "
            "refetched history are labelled outside_retention only when the fetch itself proves truncation "
            "(OKX stop_reason=page_not_full); they are not counted as matched source observations.",
            "Daily dispersion is recomputed from refetched 1h Hyperliquid + 8h OKX funding rows with an independent "
            "time-weighted-mean/population-std implementation. Dates whose OKX funding window predates the current "
            "rolling ~3-month retention are labelled outside_retention (never silently matched) when the refetch "
            "proves truncation; their persisted values remain in the immutable anchor artifact.",
            "The prior-90-date 80th-percentile threshold, type-7 quantile, current-date exclusion and the top-10% "
            "tail selection are re-derived from the persisted daily dispersion series, so they prove the arithmetic "
            "signal rule exactly but inherit any source limitation of the dispersion inputs they consume.",
            "Selection-window reproducibility checks every recorded observation's original rate against a refetched "
            "venue row (tolerance 0) and recomputes the window dispersion from those observations.",
            "Contract identity remains underlying-symbol-mapped candidate level.",
        ],
        "recomputed_at_utc": datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--underlyings", nargs="*", default=None)
    args = parser.parse_args(argv)

    result = verify(Path(args.artifact), Path(args.output), args.underlyings)
    Path(args.output).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    execution = result["execution_price_provenance"]
    funding = result["funding_settlement_provenance"]
    dispersion = result["dispersion_threshold_provenance"]
    selection = result["selection_observation_provenance"]
    print(f"SERIES_DIGEST_VERIFICATION={result['verdict']} "
          f"candle_checks={len(result['checks'])} failed={result['failed_checks']} "
          f"funding_row_mismatches={result['funding_row_count_mismatches']} "
          f"execution_price_rows={execution['rows_matched']}/{execution['rows_expected']} "
          f"failed={execution['rows_failed']} "
          f"internal_price_failed={execution['internal_price_failed']} "
          f"funding_settlements={funding['rows_matched']}/{funding['rows_expected']} "
          f"outside_retention={funding['rows_outside_retention']} "
          f"failed={funding['rows_failed']} "
          f"dispersion_rows={dispersion['dispersion_rows_matched']}/{dispersion['dispersion_rows_expected']} "
          f"dispersion_outside_retention={dispersion['dispersion_rows_outside_retention']} "
          f"dispersion_failed={dispersion['dispersion_rows_failed']} "
          f"threshold_rows={dispersion['threshold_rows_matched']}/{dispersion['threshold_rows_expected']} "
          f"threshold_failed={dispersion['threshold_rows_failed']} "
          f"selection_rows={dispersion['selection_rows_matched']}/{dispersion['selection_rows_expected']} "
          f"selection_failed={dispersion['selection_rows_failed']} "
          f"selection_observations={selection['observation_rows_matched']}/"
          f"{selection['observation_rows_expected']} failed={selection['observation_rows_failed']} "
          f"selection_dispersions={selection['underlying_windows_matched']}/"
          f"{selection['underlying_windows_expected']}")
    for name in result["failed_check_names"]:
        print(f"  FAILED {name}")
    for row in execution["rows"]:
        if not row["passed"]:
            print(f"  PRICE_MISMATCH signal={row['signal_index']} {row['underlying']} {row['venue']} "
                  f"{row['role']} {row['timestamp_utc']} recorded=({row['recorded_open']},{row['recorded_close']}) "
                  f"refetched=({row['refetched_open']},{row['refetched_close']})")
    for row in execution["internal_checks"]:
        if not row["passed"]:
            print(f"  INTERNAL_PRICE_MISMATCH signal={row['signal_index']} {row['underlying']} {row['venue']} "
                  f"{row['role']} {row['timestamp_utc']} signal={row['recorded_signal_price']} "
                  f"candle={row['recorded_candle_open']}")
    for row in funding["rows"]:
        if not row["passed"]:
            print(f"  FUNDING_MISMATCH signal={row['signal_index']} {row['underlying']} {row['venue']} "
                  f"{row['settlement_time_utc']} status={row['status']} "
                  f"recorded_rate={row['recorded_rate']} refetched_rate={row['refetched_rate']} "
                  f"interval_matches={row['interval_matches_venue']} arithmetic={row['arithmetic_reproduces']}")
    for row in dispersion["dispersion_rows"]:
        if not row["passed"]:
            print(f"  DISPERSION_MISMATCH {row['date_utc']} {row['underlying']} status={row['status']} "
                  f"recorded={row['recorded_dispersion']} recomputed={row['recomputed_dispersion']}")
    for row in dispersion["threshold_rows"]:
        if not row["passed"]:
            print(f"  THRESHOLD_MISMATCH {row['date_utc']} {row['underlying']} "
                  f"recorded={row['recorded_prior_threshold']} recomputed={row['recomputed_prior_threshold']}")
    for row in dispersion["selection_rows"]:
        if not row["passed"]:
            print(f"  SELECTION_MISMATCH {row['date_utc']} recorded={row['recorded_selected']} "
                  f"recomputed={row['recomputed_selected']}")
    for row in selection["rows"]:
        if not row["passed"]:
            print(f"  SELECTION_OBSERVATION_MISMATCH selection={row['selection_index']} {row['underlying']} "
                  f"{row['venue']} {row['timestamp_utc']} status={row['status']} "
                  f"recorded_rate={row['recorded_original_rate']} refetched_rate={row['refetched_rate']}")
    for row in selection["dispersion_rows"]:
        if not row["passed"]:
            print(f"  SELECTION_DISPERSION_MISMATCH selection={row['selection_index']} {row['underlying']} "
                  f"recorded={row['recorded_dispersion']} recomputed={row['recomputed_dispersion']} "
                  f"evidence_series={row['dispersion_evidence_value']}")
    return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
