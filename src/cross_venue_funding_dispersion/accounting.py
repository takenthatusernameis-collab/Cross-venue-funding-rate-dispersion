"""Pure accounting helpers with explicit funding and execution-cost signs."""
from __future__ import annotations
import math


def _finite(name: str, value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def funding_cash_flow(side: int, notional: float, funding_rate: float) -> float:
    """Funding cash flow: side=+1 long, -1 short; positive rate means long pays."""
    if side not in (-1, 1):
        raise ValueError("side must be +1 (long) or -1 (short)")
    amount = _finite("notional", notional)
    rate = _finite("funding_rate", funding_rate)
    if amount < 0:
        raise ValueError("notional must be non-negative")
    return -side * amount * rate


def pair_funding_cash_flow(notional_per_leg: float, long_rate: float, short_rate: float) -> float:
    """Net funding for equal-notional long-low-rate / short-high-rate legs."""
    return funding_cash_flow(1, notional_per_leg, long_rate) + funding_cash_flow(-1, notional_per_leg, short_rate)


def price_pnl(side: int, entry_notional: float, entry_price: float, exit_price: float) -> float:
    """Price PnL sized by entry notional; excludes funding and costs."""
    if side not in (-1, 1):
        raise ValueError("side must be +1 (long) or -1 (short)")
    notional, entry, exit_ = (_finite("entry_notional", entry_notional), _finite("entry_price", entry_price), _finite("exit_price", exit_price))
    if notional < 0 or entry <= 0 or exit_ <= 0:
        raise ValueError("notional must be non-negative and prices must be positive")
    return side * notional * (exit_ / entry - 1.0)


def execution_cost(notional: float, fee_bps: float, slippage_bps: float) -> float:
    """One-side cost in quote currency; apply for each leg and each fill."""
    amount, fee, slip = (_finite("notional", notional), _finite("fee_bps", fee_bps), _finite("slippage_bps", slippage_bps))
    if amount < 0 or fee < 0 or slip < 0:
        raise ValueError("notional and cost basis points must be non-negative")
    return amount * (fee + slip) / 10_000.0
