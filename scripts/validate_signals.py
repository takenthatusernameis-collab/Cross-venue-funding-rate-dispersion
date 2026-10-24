"""Offline conformance check for signal helpers (standard library only)."""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.signals import (
    normalize_funding_rate,
    time_weighted_mean,
    dispersion_from_venue_histories,
    linear_quantile,
    prior_daily_threshold,
    select_top_dispersion,
)


def check(cond, msg):
    if not cond:
        print("FAIL:", msg)
        sys.exit(1)


def expect_error(fn, args, msg="", kwargs=None):
    if kwargs is None:
        kwargs = {}
    try:
        fn(*args, **kwargs)
        check(False, msg)
    except ValueError:
        pass


def main():
    # normalize_funding_rate: linear 8-hour equivalence
    check(math.isclose(normalize_funding_rate(0.01, 8), 0.01), "8h rate unchanged")
    check(math.isclose(normalize_funding_rate(0.01, 4), 0.02), "4h doubles to 8h")
    check(math.isclose(normalize_funding_rate(0.01, 24), 0.01 / 3.0), "24h thirds to 8h")
    check(normalize_funding_rate(-0.01, 8) == -0.01, "negative rate preserves sign")
    expect_error(normalize_funding_rate, (float("nan"), 8), "non-finite rate accepted")
    expect_error(normalize_funding_rate, (0.01, 0), "zero interval accepted")
    expect_error(normalize_funding_rate, (0.01, -1), "negative interval accepted")

    # time_weighted_mean: causal, staleness fail-closed
    base = "2024-01-01T00:00:00Z"
    obs = [
        {"timestamp": base, "rate_8h": 0.01},
        {"timestamp": "2024-01-01T02:00:00Z", "rate_8h": 0.02},
    ]
    check(math.isclose(time_weighted_mean(obs, base, "2024-01-01T04:00:00Z", max_staleness_hours=4), 0.015), "twm known answer")
    check(time_weighted_mean(obs, base, "2024-01-01T07:00:00Z", max_staleness_hours=1) is None, "staleness fail-close")
    try:
        time_weighted_mean(obs, "2024-01-01T00:00:00", "2024-01-01T01:00:00Z", max_staleness_hours=4)
        check(False, "naive start accepted")
    except ValueError:
        pass
    check(time_weighted_mean([], base, "2024-01-01T01:00:00Z", max_staleness_hours=4) is None, "empty none")

    # dispersion_from_venue_histories
    hist = {
        "A": [
            {"timestamp": base, "rate_8h": 0.01},
            {"timestamp": "2024-01-01T02:00:00Z", "rate_8h": 0.03},
        ],
        "B": [{"timestamp": base, "rate_8h": 0.02}],
    }
    std, means = dispersion_from_venue_histories(hist, base, "2024-01-01T04:00:00Z", minimum_venues=2, max_staleness_hours=4)
    check(std is not None and len(means) == 2, "dispersion two venues")
    std1, _ = dispersion_from_venue_histories({"A": hist["A"]}, base, "2024-01-01T04:00:00Z", minimum_venues=2, max_staleness_hours=4)
    check(std1 is None, "below minimum venues none")
    expect_error(dispersion_from_venue_histories, (hist, base, "2024-01-01T04:00:00Z"), "minimum_venues=1 accepted", {"minimum_venues": 1, "max_staleness_hours": 4})

    # linear_quantile: type-7, no fallback
    check(math.isclose(linear_quantile([1, 2, 3, 4], 50), 2.5), "median")
    check(linear_quantile([1, 2, 3], 50, minimum_observations=5) is None, "insufficient none")
    expect_error(linear_quantile, ([1, 2], 150), "percentile >100 accepted")
    expect_error(linear_quantile, ([1, 2], 50), "minimum_observations=0 accepted", {"minimum_observations": 0})

    # prior_daily_threshold: excludes current date, excludes >23:00
    samples = [
        {"date": "2024-01-01", "snapshot_time_utc": "23:00:00", "dispersion": 0.5},
        {"date": "2024-01-01", "snapshot_time_utc": "23:30:00", "dispersion": 0.9},
        {"date": "2024-01-02", "snapshot_time_utc": "22:00:00", "dispersion": 0.7},
    ]
    thr = prior_daily_threshold(samples, "2024-01-02", 50, lookback_days=90, minimum_observations=1)
    check(thr == 0.5, "current date excluded, <=23:00 latest")
    expect_error(prior_daily_threshold, (samples, "2024-01-02", 50), "lookback 0 accepted", {"lookback_days": 0, "minimum_observations": 1})

    # select_top_dispersion: deterministic tie-break, threshold filter, fraction ceil
    values = {"B": 0.5, "A": 0.5, "C": 0.3}
    check(select_top_dispersion(values, 0.4, 0.5) == ["A", "B"], "tie-break by asset id")
    check(select_top_dispersion(values, None, 0.5) == [], "none threshold empty")
    check(select_top_dispersion(values, 0.6, 0.5) == [], "all below threshold empty")
    expect_error(select_top_dispersion, (values, 0.4, 0), "fraction 0 accepted")

    print("SIGNALS_VALIDATION=PASS")


if __name__ == "__main__":
    main()
