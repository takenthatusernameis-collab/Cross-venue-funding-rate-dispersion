"""Offline conformance check for point-in-time universe ranking (standard library only)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.universe import next_ranked_cohort, rank_point_in_time


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
    records = [
        {"asset": "AAA", "market_cap_usd": 100, "as_of": "2024-01-01T00:00:00Z", "published_at": "2024-01-01T01:00:00Z"},
        {"asset": "BBB", "market_cap_usd": 200, "as_of": "2024-01-01T00:00:00Z", "published_at": "2024-01-01T01:00:00Z"},
        {"asset": "AAA", "market_cap_usd": 150, "as_of": "2024-02-01T00:00:00Z", "published_at": "2024-02-01T01:00:00Z"},
        {"asset": "CCC", "market_cap_usd": 150, "as_of": "2024-02-01T00:00:00Z", "published_at": "2024-02-01T01:00:00Z"},
        {"asset": "AAA", "market_cap_usd": 250, "as_of": "2024-02-10T00:00:00Z", "published_at": "2024-02-10T01:00:00Z"},
        {"asset": "FUTURE", "market_cap_usd": 999, "as_of": "2025-01-01T00:00:00Z", "published_at": "2025-01-01T01:00:00Z"},
        {"asset": "LATE", "market_cap_usd": 888, "as_of": "2024-02-01T00:00:00Z", "published_at": "2024-03-01T00:00:00Z"},
        {"asset": "BAD", "market_cap_usd": float("nan"), "as_of": "2024-01-01T00:00:00Z", "published_at": "2024-01-01T00:00:00Z"},
        {"asset": "NEG", "market_cap_usd": -5.0, "as_of": "2024-01-01T00:00:00Z", "published_at": "2024-01-01T00:00:00Z"},
        {"asset": "MISSING", "as_of": "2024-01-01T00:00:00Z", "published_at": "2024-01-01T00:00:00Z"},
    ]

    # Point-in-time admissibility: effective and publication both <= snapshot
    ranked = rank_point_in_time(records, "2024-02-15T00:00:00Z")
    assets = [x["asset"] for x in ranked]
    check("FUTURE" not in assets, "future effective record admitted")
    check("LATE" not in assets, "late-published record admitted")
    check("BAD" not in assets and "NEG" not in assets and "MISSING" not in assets, "invalid cap record admitted")

    # Descending cap, ranks from 1, deterministic asset-id tie-break
    check([x["rank"] for x in ranked] == [1, 2, 3], "ranks not from 1")
    check(assets == ["BBB", "AAA", "CCC"], "not descending cap with asset-id tie-break")
    check(ranked[2]["market_cap_usd"] == 150, "tie-break cap value wrong")

    # Record-order immateriality
    shuffled = list(reversed(records))
    check([x["asset"] for x in rank_point_in_time(shuffled, "2024-02-15T00:00:00Z")] == assets, "record order affects result")

    # Latest effective/published supersession per asset
    ranked_later = rank_point_in_time(records, "2024-02-20T00:00:00Z")
    check([x["asset"] for x in ranked_later] == ["BBB", "AAA", "CCC"], "supersession not applied")

    # next_ranked_cohort: batch windows, no rank gaps, cursor resume
    full = [{"rank": i, "asset": f"A{i}"} for i in range(1, 11)]
    batches = []
    cursor = 0
    while True:
        batch = next_ranked_cohort(full, cursor, 3)
        if not batch:
            break
        batches.extend(batch)
        cursor = batch[-1]["rank"]
    check([x["asset"] for x in batches] == [f"A{i}" for i in range(1, 11)], "batches do not cover all ranks")

    # Rank frontier gap fail-closed
    expect_error(next_ranked_cohort, ([{"rank": 1, "asset": "A1"}, {"rank": 3, "asset": "A3"}], 1, 2), "rank gap accepted")

    # Bad cursor/batch fail-closed
    expect_error(next_ranked_cohort, ([], -1, 2), "negative cursor accepted")
    expect_error(next_ranked_cohort, ([], 0, 0), "zero batch accepted")
    expect_error(next_ranked_cohort, ([{"rank": 1, "asset": "A1"}, {"rank": 1, "asset": "A2"}], 0, 2), "duplicate ranks accepted")

    print("UNIVERSE_VALIDATION=PASS")


if __name__ == "__main__":
    main()
