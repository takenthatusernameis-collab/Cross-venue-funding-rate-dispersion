"""Offline conformance check for accounting helpers (standard library only)."""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.accounting import (
    funding_cash_flow, pair_funding_cash_flow, price_pnl, execution_cost,
)


def check(cond, msg):
    if not cond:
        print("FAIL:", msg)
        sys.exit(1)


def main():
    # funding sign conventions
    check(funding_cash_flow(1, 100.0, 0.01) == -1.0, "long pays on positive rate")
    check(funding_cash_flow(1, 100.0, -0.01) == 1.0, "long receives on negative rate")
    check(funding_cash_flow(-1, 100.0, 0.01) == 1.0, "short receives on positive rate")
    check(funding_cash_flow(-1, 100.0, -0.01) == -1.0, "short pays on negative rate")
    check(funding_cash_flow(1, 0.0, 0.01) == 0.0, "zero notional")
    check(pair_funding_cash_flow(100.0, 0.01, 0.02) == funding_cash_flow(1, 100.0, 0.01) + funding_cash_flow(-1, 100.0, 0.02), "pair funding")

    # price pnl
    check(math.isclose(price_pnl(1, 100.0, 100.0, 110.0), 10.0), "long price pnl")
    check(math.isclose(price_pnl(-1, 100.0, 100.0, 95.0), 5.0), "short price pnl")
    check(price_pnl(1, 0.0, 100.0, 110.0) == 0.0, "zero notional price")

    # execution cost
    check(math.isclose(execution_cost(100.0, 10.0, 5.0), 0.15), "exec cost")
    check(execution_cost(0.0, 10.0, 5.0) == 0.0, "zero notional cost")
    check(execution_cost(100.0, 0.0, 0.0) == 0.0, "zero bps")

    # invalid inputs fail-closed
    for fn, args in [
        (funding_cash_flow, (2, 100.0, 0.01)),
        (funding_cash_flow, (1, -1.0, 0.01)),
        (funding_cash_flow, (1, 100.0, float("nan"))),
        (price_pnl, (2, 100.0, 100.0, 110.0)),
        (price_pnl, (1, 100.0, 0.0, 110.0)),
        (price_pnl, (1, 100.0, 100.0, 0.0)),
        (price_pnl, (1, -1.0, 100.0, 110.0)),
        (execution_cost, (-1.0, 1.0, 1.0)),
        (execution_cost, (1.0, -1.0, 1.0)),
        (execution_cost, (1.0, 1.0, float("inf"))),
    ]:
        try:
            fn(*args)
            check(False, "invalid input accepted")
        except ValueError:
            pass

    print("ACCOUNTING_VALIDATION=PASS")


if __name__ == "__main__":
    main()
