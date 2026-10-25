#!/usr/bin/env python3
"""Offline conformance check for backtest harness (standard library only)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.backtest import (
    allocate_portfolio_pairs,
    compute_portfolio_gross_exposure,
    run_backtest_skeleton,
)


def validate_backtest() -> list[str]:
    errors = []
    # Equal-notional pair allocation splits equity evenly across both legs.
    alloc = allocate_portfolio_pairs(100.0, ["BTC", "ETH"])
    expected_notional = 100.0 * 1.0 / (2.0 * 2)
    if set(alloc) != {"BTC", "ETH"}:
        errors.append("allocation missing assets")
    elif not all(abs(v - expected_notional) < 1e-12 for v in alloc.values()):
        errors.append("equal notional allocation wrong")
    # Gross exposure across both legs equals equity at gross multiple 1.0.
    gross = compute_portfolio_gross_exposure({}, alloc)
    if abs(gross - 100.0) > 1e-12:
        errors.append("gross exposure wrong")
    # Zero gross multiple allocates nothing.
    if allocate_portfolio_pairs(100.0, ["BTC"], gross_multiple=0.0) != {}:
        errors.append("zero multiple should allocate nothing")
    # Single asset: both legs share equity (50.0 per leg at multiple 1.0).
    alloc1 = allocate_portfolio_pairs(100.0, ["BTC"])
    if not alloc1 or abs(alloc1["BTC"] - 50.0) > 1e-12:
        errors.append("single asset allocation wrong")
    # run_backtest_skeleton with a valid pair returns a structured result.
    result = run_backtest_skeleton(
        equity=100.0,
        pairs=[{
            "asset_long": "BTC",
            "asset_short": "ETH",
            "entry_price_long": 100.0,
            "exit_price_long": 110.0,
            "entry_price_short": 100.0,
            "exit_price_short": 95.0,
            "funding_rate_long": 0.001,
            "funding_rate_short": 0.0005,
        }],
        signal_time="2024-01-01T00:00:00Z",
        next_open_time="2024-01-01T01:00:00Z",
        fee_bps_per_side=5.0,
        slippage_bps_per_side=5.0,
    )
    if not isinstance(result, dict):
        errors.append("backtest result not dict")
    elif "total_net_pnl" not in result or "gross_exposure" not in result:
        errors.append("backtest missing keys")
    # Fail-closed: next_open before signal raises ValueError.
    try:
        run_backtest_skeleton(
            equity=100.0,
            pairs=[],
            signal_time="2024-01-01T02:00:00Z",
            next_open_time="2024-01-01T01:00:00Z",
            fee_bps_per_side=0.0,
            slippage_bps_per_side=0.0,
        )
        errors.append("open before signal accepted")
    except ValueError:
        pass
    except Exception as exc:
        errors.append(f"open before signal raised wrong type: {exc}")
    # Fail-closed: negative equity raises ValueError.
    try:
        allocate_portfolio_pairs(-1.0, ["BTC"])
        errors.append("negative equity accepted")
    except ValueError:
        pass
    except Exception as exc:
        errors.append(f"negative equity raised wrong type: {exc}")
    return errors


def main() -> int:
    errors = validate_backtest()
    if errors:
        for e in errors:
            print("FAIL:", e)
        sys.exit(1)
    print("BACKTEST_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
