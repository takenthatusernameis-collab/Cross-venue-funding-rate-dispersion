"""Offline conformance check for portfolio allocation (standard library only)."""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.portfolio import allocate_equal_notional_pairs


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
    # Known answer: equal notional per leg, sorted asset ids, gross <= equity * multiple
    alloc = allocate_equal_notional_pairs(1000.0, ["B", "A", "C"])
    check(list(alloc) == ["A", "B", "C"], "assets not sorted")
    check(len(alloc) == 3, "wrong asset count")
    check(math.isclose(alloc["A"], 1000.0 / 6.0), "notional per leg wrong")
    check(math.isclose(sum(alloc.values()) * 2.0, 1000.0), "gross exposure not equity*1.0x")

    # Hard cap at exactly 1.0x is allowed; above 1.0x rejected
    alloc_cap = allocate_equal_notional_pairs(5000.0, ["BTC", "ETH", "SOL"], gross_multiple=1.0)
    check(math.isclose(sum(alloc_cap.values()) * 2.0, 5000.0), "1.0x cap not satisfied")
    expect_error(allocate_equal_notional_pairs, (1000.0, ["A"],), "gross_multiple=1.1 accepted", kwargs={"gross_multiple": 1.1})
    expect_error(allocate_equal_notional_pairs, (1000.0, ["A"],), "gross_multiple=-0.1 accepted", kwargs={"gross_multiple": -0.1})

    # Below-cap multiples scale notional; gross equals equity*multiple
    alloc_half = allocate_equal_notional_pairs(1000.0, ["A", "B"], gross_multiple=0.5)
    check(math.isclose(sum(alloc_half.values()) * 2.0, 500.0), "0.5x multiple gross wrong")

    # Zero edge cases return empty without error
    check(allocate_equal_notional_pairs(1000.0, []) == {}, "empty assets not empty dict")
    check(allocate_equal_notional_pairs(0.0, ["A"]) == {}, "zero equity not empty dict")
    check(allocate_equal_notional_pairs(1000.0, ["A"], gross_multiple=0.0) == {}, "zero multiple not empty dict")

    # Duplicate assets fail-closed
    expect_error(allocate_equal_notional_pairs, (1000.0, ["A", "A"]), "duplicate assets accepted")

    # Invalid equity fail-closed
    expect_error(allocate_equal_notional_pairs, (-1.0, ["A"]), "negative equity accepted")
    expect_error(allocate_equal_notional_pairs, (float("nan"), ["A"]), "non-finite equity accepted")
    expect_error(allocate_equal_notional_pairs, (float("inf"), ["A"]), "infinite equity accepted")

    # Determinism
    check(allocate_equal_notional_pairs(1000.0, ["Z", "A", "M"]) == allocate_equal_notional_pairs(1000.0, ["Z", "A", "M"]), "non-deterministic output")

    print("PORTFOLIO_VALIDATION=PASS")


if __name__ == "__main__":
    main()
