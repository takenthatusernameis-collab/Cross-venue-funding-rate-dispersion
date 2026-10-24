"""Deterministic equal-notional pair PnL ledger with separated attribution.

Long price PnL, short price PnL, net price/basis PnL, funding cash flow,
per-leg fees, per-leg slippage and total net PnL are kept as separate ledger
fields; funding is never folded into price returns. The hard gross-exposure
cap (<= 1.0x equity) is enforced fail-closed. Funding applies only while the
position is open at settlement; a missed settlement pays zero and is never an
invented fill. Pure, deterministic, standard library only; no network calls.
"""
from __future__ import annotations

import math

from cross_venue_funding_dispersion.accounting import (
    execution_cost,
    funding_cash_flow,
    price_pnl,
)


def compute_pair_pnl(
    *,
    equity: float,
    notional_per_leg: float,
    entry_price_long: float,
    exit_price_long: float,
    entry_price_short: float,
    exit_price_short: float,
    funding_rate_long: float,
    funding_rate_short: float,
    fee_bps_per_side: float,
    slippage_bps_per_side: float,
    gross_multiple: float = 1.0,
    position_open_at_settlement: bool = True,
    fills_per_leg: int = 2,
) -> dict[str, float]:
    """Return a fully attributed pair PnL ledger with separated fields."""
    equity_value = float(equity)
    if not math.isfinite(equity_value) or equity_value < 0:
        raise ValueError("equity must be finite and non-negative")
    notional = float(notional_per_leg)
    if not math.isfinite(notional) or notional < 0:
        raise ValueError("notional_per_leg must be finite and non-negative")
    if not math.isfinite(gross_multiple) or not 0 <= gross_multiple <= 1.0:
        raise ValueError("gross_multiple must be in [0, 1.0]")
    if not isinstance(fills_per_leg, int) or isinstance(fills_per_leg, bool) or fills_per_leg < 1:
        raise ValueError("fills_per_leg must be a positive integer")
    for name, value in (
        ("entry_price_long", entry_price_long),
        ("exit_price_long", exit_price_long),
        ("entry_price_short", entry_price_short),
        ("exit_price_short", exit_price_short),
    ):
        price = float(value)
        if not math.isfinite(price) or price <= 0:
            raise ValueError(f"{name} must be finite and positive")
    for name, value in (("funding_rate_long", funding_rate_long), ("funding_rate_short", funding_rate_short)):
        rate = float(value)
        if not math.isfinite(rate):
            raise ValueError(f"{name} must be finite")
    for name, value in (("fee_bps_per_side", fee_bps_per_side), ("slippage_bps_per_side", slippage_bps_per_side)):
        cost = float(value)
        if not math.isfinite(cost) or cost < 0:
            raise ValueError(f"{name} must be finite and non-negative")

    long_price_pnl = price_pnl(1, notional, entry_price_long, exit_price_long)
    short_price_pnl = price_pnl(-1, notional, entry_price_short, exit_price_short)
    net_price_basis_pnl = long_price_pnl + short_price_pnl

    if position_open_at_settlement:
        funding = (
            funding_cash_flow(1, notional, funding_rate_long)
            + funding_cash_flow(-1, notional, funding_rate_short)
        )
    else:
        funding = 0.0

    fills = 2 * fills_per_leg
    fees = execution_cost(notional, fee_bps_per_side, 0.0) * fills
    slippage = execution_cost(notional, 0.0, slippage_bps_per_side) * fills

    total_net_pnl = net_price_basis_pnl + funding - fees - slippage
    gross_exposure = 2.0 * notional
    gross_cap = equity_value * gross_multiple
    if gross_exposure > gross_cap:
        raise ValueError(f"gross exposure {gross_exposure} exceeds cap {gross_cap}")

    return {
        "long_price_pnl": long_price_pnl,
        "short_price_pnl": short_price_pnl,
        "net_price_basis_pnl": net_price_basis_pnl,
        "funding_cash_flow": funding,
        "fees": fees,
        "slippage": slippage,
        "total_net_pnl": total_net_pnl,
        "gross_exposure": gross_exposure,
        "gross_exposure_cap": gross_cap,
    }
