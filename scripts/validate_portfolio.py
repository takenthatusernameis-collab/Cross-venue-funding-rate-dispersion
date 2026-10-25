#!/usr/bin/env python3
"""Offline conformance check for portfolio construction (standard library only)."""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.portfolio import allocate_equal_notional_pairs


def validate_portfolio() -> list[str]:
    errors = []
    # Equal notional per leg: equity split across both legs of each pair.
    alloc = allocate_equal_notional_pairs(100.0, ["BTC", "ETH"])
    expected = 100.0 / (2.0 * 2)
    if set(alloc) != {"BTC", "ETH"}:
        errors.append("allocation missing assets")
    elif not all(abs(v - expected) < 1e-12 for v in alloc.values()):
        errors.append("equal notional allocation wrong")
    # Zero equity or zero gross multiple allocates nothing.
    if allocate_equal_notional_pairs(0.0, ["BTC"]) != {}:
        errors.append("zero equity should allocate nothing")
    if allocate_equal_notional_pairs(100.0, ["BTC"], gross_multiple=0.0) != {}:
        errors.append("zero multiple should allocate nothing")
    # Single asset: both legs share equity (50.0 per leg at multiple 1.0).
    alloc1 = allocate_equal_notional_pairs(100.0, ["BTC"])
    if not alloc1 or abs(alloc1["BTC"] - 50.0) > 1e-12:
        errors.append("single asset allocation wrong")
    # Fail-closed: non-finite equity rejected.
    try:
        allocate_equal_notional_pairs(float("nan"), ["BTC"])
        errors.append("nan equity accepted")
    except ValueError:
        pass
    except Exception as exc:
        errors.append(f"nan equity raised wrong type: {exc}")
    # Fail-closed: gross multiple above 1.0 rejected.
    try:
        allocate_equal_notional_pairs(100.0, ["BTC"], gross_multiple=1.5)
        errors.append("gross multiple >1 accepted")
    except ValueError:
        pass
    except Exception as exc:
        errors.append(f"gross multiple raised wrong type: {exc}")
    # Fail-closed: duplicate assets rejected.
    try:
        allocate_equal_notional_pairs(100.0, ["BTC", "BTC"])
        errors.append("duplicate assets accepted")
    except ValueError:
        pass
    except Exception as exc:
        errors.append(f"duplicate assets raised wrong type: {exc}")
    return errors


def main() -> int:
    errors = validate_portfolio()
    if errors:
        for e in errors:
            print("FAIL:", e)
        sys.exit(1)
    print("PORTFOLIO_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
