"""Offline conformance check for the pair PnL ledger (standard library only)."""
import math
import sys

from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.pair_pnl import compute_pair_pnl


def check(cond, msg):
    if not cond:
        print("FAIL:", msg)
        sys.exit(1)


def main():
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
    check(set(ledger) == required, "missing ledger fields")
    check(math.isclose(ledger["long_price_pnl"], 5.0), "long price pnl")
    check(math.isclose(ledger["short_price_pnl"], 2.5), "short price pnl")
    check(math.isclose(ledger["net_price_basis_pnl"], 7.5), "net price basis pnl")
    check(ledger["gross_exposure"] <= ledger["gross_exposure_cap"], "gross cap")
    check(math.isclose(ledger["total_net_pnl"],
                      ledger["net_price_basis_pnl"] + ledger["funding_cash_flow"]
                      - ledger["fees"] - ledger["slippage"]), "total net pnl")

    # missed settlement pays zero funding
    missed = compute_pair_pnl(
        equity=100.0, notional_per_leg=50.0,
        entry_price_long=100.0, exit_price_long=100.0,
        entry_price_short=100.0, exit_price_short=100.0,
        funding_rate_long=0.01, funding_rate_short=0.005,
        fee_bps_per_side=0.0, slippage_bps_per_side=0.0,
        position_open_at_settlement=False,
    )
    check(missed["funding_cash_flow"] == 0.0, "missed settlement funding zero")

    # gross cap fail-closed
    try:
        compute_pair_pnl(
            equity=100.0, notional_per_leg=60.0,
            entry_price_long=100.0, exit_price_long=100.0,
            entry_price_short=100.0, exit_price_short=100.0,
            funding_rate_long=0.0, funding_rate_short=0.0,
            fee_bps_per_side=0.0, slippage_bps_per_side=0.0,
        )
        check(False, "gross cap not enforced")
    except ValueError:
        pass

    # invalid inputs fail-closed
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
            check(False, "invalid input accepted")
        except ValueError:
            pass

    print("PAIR_PNL_VALIDATION=PASS")


if __name__ == "__main__":
    main()
