#!/usr/bin/env python3
"""Offline conformance check for funding settlement accounting (standard library only)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.accounting import (
    execution_cost,
    funding_cash_flow,
    pair_funding_cash_flow,
    price_pnl,
)
from cross_venue_funding_dispersion.signals import normalize_funding_rate


def validate_accounting() -> list[str]:
    errors = []
    try:
        # Positive funding rate: long pays, short receives.
        if funding_cash_flow(1, 100.0, 0.01) != -1.0:
            errors.append("long funding sign/cash flow wrong")
        if funding_cash_flow(-1, 100.0, 0.01) != 1.0:
            errors.append("short funding sign wrong")
        # Negative funding rate: long receives, short pays.
        if funding_cash_flow(1, 100.0, -0.01) != 1.0:
            errors.append("negative long funding sign wrong")
        if funding_cash_flow(-1, 100.0, -0.01) != -1.0:
            errors.append("negative short funding sign wrong")
        # Equal-notional pair: long low rate, short high rate collects carry.
        if pair_funding_cash_flow(1000.0, -0.0005, 0.001) != 1.5:
            errors.append("pair funding carry wrong")
        if pair_funding_cash_flow(500.0, 0.002, -0.001) != -1.5:
            errors.append("pair funding symmetric wrong")
        if pair_funding_cash_flow(100.0, 0.0003, 0.0003) != 0.0:
            errors.append("pair funding equal rates not zero")
        # Price PnL is separate from funding and costs.
        if abs(price_pnl(1, 1000.0, 100.0, 110.0) - 100.0) > 1e-12:
            errors.append("long price pnl wrong")
        if abs(price_pnl(-1, 1000.0, 100.0, 110.0) - (-100.0)) > 1e-12:
            errors.append("short price pnl wrong")
        # Execution cost applies per side and per fill.
        if execution_cost(1000.0, 5.0, 5.0) != 1.0:
            errors.append("execution cost wrong")
        if execution_cost(0.0, 10.0, 10.0) != 0.0:
            errors.append("zero notional cost wrong")
    except Exception as exc:
        errors.append(f"accounting basic raised: {exc}")

    # 8-hour normalization with actual venue intervals (funding-accounting skill).
    try:
        # Hyperliquid hourly (1h) rate normalizes to 8h equivalent by x8.
        if abs(normalize_funding_rate(0.0001, 1.0) - 0.0008) > 1e-15:
            errors.append("HL 1h->8h normalization wrong")
        # OKX 8h rate is already 8h equivalent (identity).
        if abs(normalize_funding_rate(0.0002, 8.0) - 0.0002) > 1e-15:
            errors.append("OKX 8h normalization wrong")
        # Linear: r_8h = r_event * 8 / interval_hours
        if abs(normalize_funding_rate(0.001, 4.0) - 0.002) > 1e-15:
            errors.append("4h->8h normalization wrong")
    except Exception as exc:
        errors.append(f"normalization check raised: {exc}")

    # Invalid normalization inputs must fail closed.
    for bad_args in [(0.001, 0), (float("nan"), 8), (0.001, -1)]:
        try:
            normalize_funding_rate(*bad_args)
            errors.append("invalid normalization input accepted")
        except ValueError:
            pass
        except Exception as exc:
            errors.append(f"invalid normalization raised wrong type: {exc}")

    # Invalid inputs must fail closed with ValueError.
    for fn, args in [
        (funding_cash_flow, (0, 100.0, 0.01)),
        (funding_cash_flow, (1, 100.0, float("nan"))),
        (funding_cash_flow, (2, 100.0, 0.01)),
        (funding_cash_flow, (1, -1.0, 0.01)),
        (execution_cost, (1000.0, -1.0, 2.0)),
        (execution_cost, (1000.0, 0.0, -0.1)),
        (price_pnl, (1, 100.0, 0.0, 100.0)),
        (price_pnl, (1, -1.0, 100.0, 110.0)),
        (price_pnl, (1, 100.0, float("inf"), 110.0)),
    ]:
        try:
            fn(*args)
            errors.append("invalid input accepted")
        except ValueError:
            pass
        except Exception as exc:
            errors.append(f"invalid input raised wrong type: {exc}")
    return errors


def main() -> int:
    errors = validate_accounting()
    if errors:
        for e in errors:
            print("FAIL:", e)
        sys.exit(1)
    print("ACCOUNTING_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())