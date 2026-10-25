#!/usr/bin/env python3
"""Offline conformance check for the pair PnL ledger (standard library only)."""
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.pair_pnl import compute_pair_pnl


def validate_pair_pnl() -> list[str]:
    errors = []
    try:
        ledger = compute_pair_pnl(
            equity=100.0,
            notional_per_leg=50.0,
            entry_price_long=100.0,
            exit_price_long=110.0,
            entry_price_short=100.0,
            exit_price_short=95.0,
            funding_rate_long=0.01,
            funding_rate_short=0.005,
            fee_bps_per_side=1.0,
            slippage_bps_per_side=2.0,
            fills_per_leg=2,
        )
        required = {
            "long_price_pnl", "short_price_pnl", "net_price_basis_pnl",
            "funding_cash_flow", "fees", "slippage", "total_net_pnl",
            "gross_exposure", "gross_exposure_cap",
        }
        if set(ledger) != required:
            errors.append("missing ledger fields")
        elif not math.isclose(ledger["long_price_pnl"], 5.0):
            errors.append("long price pnl")
        elif not math.isclose(ledger["short_price_pnl"], 2.5):
            errors.append("short price pnl")
        elif not math.isclose(ledger["net_price_basis_pnl"], 7.5):
            errors.append("net price basis pnl")
        elif ledger["gross_exposure"] > ledger["gross_exposure_cap"]:
            errors.append("gross cap")
        elif not math.isclose(ledger["total_net_pnl"],
                              ledger["net_price_basis_pnl"] + ledger["funding_cash_flow"]
                              - ledger["fees"] - ledger["slippage"]):
            errors.append("total net pnl")
    except Exception as exc:
        errors.append(f"ledger check raised: {exc}")

    try:
        missed = compute_pair_pnl(
            equity=100.0, notional_per_leg=50.0,
            entry_price_long=100.0, exit_price_long=100.0,
            entry_price_short=100.0, exit_price_short=100.0,
            funding_rate_long=0.01, funding_rate_short=0.005,
            fee_bps_per_side=0.0, slippage_bps_per_side=0.0,
            position_open_at_settlement=False,
        )
        if missed["funding_cash_flow"] != 0.0:
            errors.append("missed settlement funding zero")
    except Exception as exc:
        errors.append(f"missed settlement raised: {exc}")

    try:
        compute_pair_pnl(
            equity=100.0, notional_per_leg=60.0,
            entry_price_long=100.0, exit_price_long=100.0,
            entry_price_short=100.0, exit_price_short=100.0,
            funding_rate_long=0.0, funding_rate_short=0.0,
            fee_bps_per_side=0.0, slippage_bps_per_side=0.0,
        )
        errors.append("gross cap not enforced")
    except ValueError:
        pass
    except Exception as exc:
        errors.append(f"gross cap raised wrong type: {exc}")

    for kwargs in [
        dict(equity=float("nan"), notional_per_leg=1.0, entry_price_long=1.0,
             exit_price_long=1.0, entry_price_short=1.0, exit_price_short=1.0,
             funding_rate_long=0.0, funding_rate_short=0.0,
             fee_bps_per_side=0.0, slippage_bps_per_side=0.0),
        dict(equity=1.0, notional_per_leg=-1.0, entry_price_long=1.0,
             exit_price_long=1.0, entry_price_short=1.0, exit_price_short=1.0,
             funding_rate_long=0.0, funding_rate_short=0.0,
             fee_bps_per_side=0.0, slippage_bps_per_side=0.0),
        dict(equity=1.0, notional_per_leg=1.0, entry_price_long=0.0,
             exit_price_long=1.0, entry_price_short=1.0, exit_price_short=1.0,
             funding_rate_long=0.0, funding_rate_short=0.0,
             fee_bps_per_side=0.0, slippage_bps_per_side=0.0),
    ]:
        try:
            compute_pair_pnl(**kwargs)
            errors.append("invalid input accepted")
        except ValueError:
            pass
        except Exception as exc:
            errors.append(f"invalid input raised wrong type: {exc}")

    return errors


def main() -> int:
    errors = validate_pair_pnl()
    if errors:
        for e in errors:
            print("FAIL:", e)
        sys.exit(1)
    print("PAIR_PNL_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
