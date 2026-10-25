#!/usr/bin/env python3
"""Offline conformance check for funding-dispersion signal construction (standard library only)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.signals import (
    dispersion_from_venue_histories,
    linear_quantile,
    normalize_funding_rate,
    prior_daily_threshold,
    select_top_dispersion,
    time_weighted_mean,
)


def validate_signals() -> list[str]:
    errors = []
    try:
        # 8-hour normalization preserves the documented actual interval.
        if normalize_funding_rate(0.001, 4) != 0.002:
            errors.append("normalization wrong")
        # Time-weighted mean over a piecewise-constant rate series.
        rows = [
            {"timestamp": "2024-01-01T00:00:00Z", "rate_8h": 1.0},
            {"timestamp": "2024-01-01T02:00:00Z", "rate_8h": 3.0},
        ]
        if time_weighted_mean(rows, "2024-01-01T00:00:00Z", "2024-01-01T04:00:00Z",
                               max_staleness_hours=3) != 2.0:
            errors.append("time weighted mean wrong")
        # Coverage gap at start fails closed (returns None, not a fallback).
        if time_weighted_mean(rows[1:], "2024-01-01T00:00:00Z", "2024-01-01T04:00:00Z",
                              max_staleness_hours=3) is not None:
            errors.append("gap at start not fail-closed")
        # Stale change fails closed.
        stale_rows = [
            {"timestamp": "2024-01-01T00:00:00Z", "rate_8h": 1.0},
            {"timestamp": "2024-01-01T03:30:00Z", "rate_8h": 2.0},
        ]
        if time_weighted_mean(stale_rows, "2024-01-01T00:00:00Z", "2024-01-01T04:00:00Z",
                              max_staleness_hours=2) is not None:
            errors.append("stale change not fail-closed")
        # Dispersion requires at least two eligible venues.
        start = "2024-01-01T00:00:00Z"
        end = "2024-01-01T02:00:00Z"
        histories = {
            "A": [{"timestamp": start, "rate_8h": 1.0}],
            "B": [{"timestamp": start, "rate_8h": 3.0}],
        }
        disp, means = dispersion_from_venue_histories(histories, start, end,
                                                       minimum_venues=2, max_staleness_hours=3)
        if disp != 1.0 or means != {"A": 1.0, "B": 3.0}:
            errors.append("dispersion/means wrong")
        disp, _ = dispersion_from_venue_histories({"A": histories["A"]}, start, end,
                                                   minimum_venues=2, max_staleness_hours=3)
        if disp is not None:
            errors.append("insufficient venues not fail-closed")
        # Type-7 linear quantile known answer; insufficient samples -> None.
        if linear_quantile([0, 10, 20, 30], 50) != 15:
            errors.append("quantile wrong")
        if linear_quantile([1, 2], 80, minimum_observations=3) is not None:
            errors.append("quantile not fail-closed on insufficient samples")
        # Prior daily threshold uses only prior dates, one latest <=23:00 sample.
        samples = [
            {"date": "2024-01-01", "snapshot_time_utc": "22:00", "dispersion": 1.0},
            {"date": "2024-01-01", "snapshot_time_utc": "23:00", "dispersion": 2.0},
            {"date": "2024-01-01", "snapshot_time_utc": "23:30", "dispersion": 3.0},
            {"date": "2024-01-02", "snapshot_time_utc": "22:00", "dispersion": 100.0},
        ]
        if prior_daily_threshold(samples, "2024-01-02", 50, lookback_days=90,
                                minimum_observations=1) != 2.0:
            errors.append("prior daily threshold wrong")
        # Top-tail selection is deterministic with asset-id tie-break.
        if select_top_dispersion({"B": 4, "A": 4, "C": 2}, 3, 0.5) != ["A", "B"]:
            errors.append("top tail selection wrong")
        if select_top_dispersion({"A": 10}, None, 0.5) != []:
            errors.append("threshold None should yield no signal")
    except Exception as exc:
        errors.append(f"signals basic raised: {exc}")

    # Bad inputs fail closed.
    for fn, args in [
        (normalize_funding_rate, (0.001, 0)),
        (normalize_funding_rate, (float("nan"), 8)),
        (normalize_funding_rate, (0.001, -1)),
        (linear_quantile, ([1, 2], 50, minimum_observations=0)),
        (linear_quantile, ([1, 2], -1)),
        (linear_quantile, ([1, 2], 101)),
        (select_top_dispersion, ({"A": 1}, 1.0, 0)),
        (select_top_dispersion, ({"A": 1}, 1.0, 1.5)),
    ]:
        try:
            fn(*args)
            errors.append("bad input accepted")
        except ValueError:
            pass
        except Exception as exc:
            errors.append(f"bad input raised wrong type: {exc}")
    return errors


def main() -> int:
    errors = validate_signals()
    if errors:
        for e in errors:
            print("FAIL:", e)
        sys.exit(1)
    print("SIGNALS_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())