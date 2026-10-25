#!/usr/bin/env python3
"""Offline conformance check for point-in-time universe ranking (standard library only)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.universe import next_ranked_cohort, rank_point_in_time


def expect_error(fn, args, kwargs=None):
    if kwargs is None:
        kwargs = {}
    try:
        fn(*args, **kwargs)
        return False
    except ValueError:
        return True


def validate_universe() -> list[str]:
    errors = []
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

    try:
        ranked = rank_point_in_time(records, "2024-02-15T00:00:00Z")
        assets = [x["asset"] for x in ranked]
        if "FUTURE" in assets:
            errors.append("future effective record admitted")
        if "LATE" in assets:
            errors.append("late-published record admitted")
        if "BAD" in assets or "NEG" in assets or "MISSING" in assets:
            errors.append("invalid cap record admitted")
        if [x["rank"] for x in ranked] != [1, 2, 3]:
            errors.append("ranks not from 1")
        if assets != ["AAA", "BBB", "CCC"]:
            errors.append("not descending cap with asset-id tie-break")
        if ranked[2]["market_cap_usd"] != 150:
            errors.append("tie-break cap value wrong")
        shuffled = list(reversed(records))
        if [x["asset"] for x in rank_point_in_time(shuffled, "2024-02-15T00:00:00Z")] != assets:
            errors.append("record order affects result")
        ranked_later = rank_point_in_time(records, "2024-02-20T00:00:00Z")
        if [x["asset"] for x in ranked_later] != ["AAA", "BBB", "CCC"]:
            errors.append("supersession not applied")
    except Exception as exc:
        errors.append(f"universe checks raised: {exc}")

    try:
        full = [{"rank": i, "asset": f"A{i}"} for i in range(1, 11)]
        batches = []
        cursor = 0
        while True:
            batch = next_ranked_cohort(full, cursor, 3)
            if not batch:
                break
            batches.extend(batch)
            cursor = batch[-1]["rank"]
        if [x["asset"] for x in batches] != [f"A{i}" for i in range(1, 11)]:
            errors.append("batches do not cover all ranks")
    except Exception as exc:
        errors.append(f"cohort batches raised: {exc}")

    if not expect_error(next_ranked_cohort, ([{"rank": 1, "asset": "A1"}, {"rank": 3, "asset": "A3"}], 1, 2)):
        errors.append("rank gap accepted")
    if not expect_error(next_ranked_cohort, ([], -1, 2)):
        errors.append("negative cursor accepted")
    if not expect_error(next_ranked_cohort, ([], 0, 0)):
        errors.append("zero batch accepted")
    if not expect_error(next_ranked_cohort, ([{"rank": 1, "asset": "A1"}, {"rank": 1, "asset": "A2"}], 0, 2)):
        errors.append("duplicate ranks accepted")

    return errors


def main() -> int:
    errors = validate_universe()
    if errors:
        for e in errors:
            print("FAIL:", e)
        sys.exit(1)
    print("UNIVERSE_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
