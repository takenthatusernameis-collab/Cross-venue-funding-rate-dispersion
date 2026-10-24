"""Source-independent backtest engine skeleton (deterministic, no network).

Connects signals to the pair PnL ledger, uses equal-notional pair allocation
with a hard cross-pair gross-exposure <= 1.0x equity cap, enforces
closed-bar / next-open entry and settlement-timed funding, never invents
fills, and fails closed on missing data. Funding and price/basis remain
separately attributed via the pair ledger.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Any

from cross_venue_funding_dispersion.accounting import execution_cost, funding_cash_flow, price_pnl
from cross_venue_funding_dispersion.pair_pnl import compute_pair_pnl
from cross_venue_funding_dispersion.portfolio import allocate_equal_notional_pairs


def _utc(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
        value[:-1] + "+00:00" if isinstance(value, str) and value.endswith("Z") else value
    )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _finite(name: str, value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _require_finite_positive_price(name: str, value: float) -> float:
    price = float(value)
    if not math.isfinite(price) or price <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return price


def compute_portfolio_gross_exposure(equities: dict[str, float], notional_per_asset: dict[str, float]) -> float:
    """Sum gross exposure across all assets (2*n per pair leg allocation)."""
    total = 0.0
    for asset_id, notional in notional_per_asset.items():
        total += 2.0 * float(notional)
    return total


def allocate_portfolio_pairs(
    equity: float,
    asset_ids: list[str],
    *,
    gross_multiple: float = 1.0,
) -> dict[str, float]:
    """Allocate equal-notional pairs with hard cross-pair gross-exposure cap."""
    return allocate_equal_notional_pairs(equity, asset_ids, gross_multiple=gross_multiple)


def run_backtest_skeleton(
    *,
    equity: float,
    pairs: list[dict[str, Any]],
    signal_time: str | datetime,
    next_open_time: str | datetime,
    fee_bps_per_side: float,
    slippage_bps_per_side: float,
    gross_multiple: float = 1.0,
    fills_per_leg: int = 2,
    max_staleness_hours: float | None = None,
) -> dict[str, Any]:
    """Execute a source-independent backtest skeleton over equal-notional pairs.

    - Entry is enforced at or after next_open_time (closed-bar/next-open);
      signal_time must be <= next_open_time.
    - Funding is settlement-timed and applied only if position_open_at_settlement.
    - Cross-pair gross exposure <= equity * gross_multiple enforced fail-closed.
    - Missing/invalid data fails closed; no fills are invented.
    - Price/basis and funding/costs are separated via pair ledger.
    """
    equity_value = _finite("equity", equity)
    if equity_value < 0:
        raise ValueError("equity must be non-negative")
    sig_t = _utc(signal_time)
    open_t = _utc(next_open_time)
    if open_t < sig_t:
        raise ValueError("next_open_time must be >= signal_time (closed-bar/next-open)")
    if not isinstance(pairs, list):
        raise ValueError("pairs must be a list")
    fee = _finite("fee_bps_per_side", fee_bps_per_side)
    slip = _finite("slippage_bps_per_side", slippage_bps_per_side)
    if fee < 0 or slip < 0:
        raise ValueError("fee_bps_per_side and slippage_bps_per_side must be non-negative")
    if not math.isfinite(gross_multiple) or not 0 <= gross_multiple <= 1.0:
        raise ValueError("gross_multiple must be in [0, 1.0]")
    if not isinstance(fills_per_leg, int) or isinstance(fills_per_leg, bool) or fills_per_leg < 1:
        raise ValueError("fills_per_leg must be a positive integer")
    if max_staleness_hours is not None:
        stale = _finite("max_staleness_hours", max_staleness_hours)
        if stale <= 0:
            raise ValueError("max_staleness_hours must be positive")

    asset_ids: list[str] = []
    for pair in pairs:
        if not isinstance(pair, dict):
            raise ValueError("each pair must be a dict")
        for key in ("asset_long", "asset_short"):
            if key not in pair or not isinstance(pair[key], str) or not pair[key]:
                raise ValueError(f"pair missing valid {key}")
        asset_ids.extend([pair["asset_long"], pair["asset_short"]])
    if len(set(asset_ids)) != len(asset_ids):
        raise ValueError("pairs must not reuse assets (all asset_ids must be unique)")

    # Allocation uses equal-notional pairs with cap
    allocation = allocate_equal_notional_pairs(equity_value, asset_ids, gross_multiple=gross_multiple)
    notional_per_leg = 0.0
    if allocation:
        notional_per_leg = next(iter(allocation.values()))

    gross_total = compute_portfolio_gross_exposure({}, allocation)
    gross_cap = equity_value * gross_multiple
    # Cross-pair gross exposure hard cap <= 1.0x equity
    if gross_total > equity_value * 1.0 + 1e-12:
        raise ValueError(f"cross-pair gross exposure exceeds cap")
    if gross_total > gross_cap + 1e-12:
        raise ValueError(f"gross exposure {gross_total} exceeds cap {gross_cap}")

    ledgers: list[dict[str, Any]] = []
    for pair in pairs:
        asset_long = pair["asset_long"]
        asset_short = pair["asset_short"]
        notional_l = allocation.get(asset_long)
        notional_s = allocation.get(asset_short)
        if notional_l is None or notional_s is None:
            raise ValueError("allocation missing pair leg")
        if not math.isclose(notional_l, notional_s):
            raise ValueError("equal-notional pair requires equal legs")
        for key in (
            "entry_price_long",
            "exit_price_long",
            "entry_price_short",
            "exit_price_short",
            "funding_rate_long",
            "funding_rate_short",
        ):
            if key not in pair:
                raise ValueError(f"pair missing {key}")
        position_open_at_settlement = bool(pair.get("position_open_at_settlement", True))
        if "settlement_time" in pair and pair["settlement_time"] is not None:
            sett_t = _utc(pair["settlement_time"])
            if open_t > sett_t:
                # cannot settle if not yet open; treat as missed settlement
                position_open_at_settlement = False
        ledger = compute_pair_pnl(
            equity=equity_value,
            notional_per_leg=notional_l,
            entry_price_long=_require_finite_positive_price("entry_price_long", pair["entry_price_long"]),
            exit_price_long=_require_finite_positive_price("exit_price_long", pair["exit_price_long"]),
            entry_price_short=_require_finite_positive_price("entry_price_short", pair["entry_price_short"]),
            exit_price_short=_require_finite_positive_price("exit_price_short", pair["exit_price_short"]),
            funding_rate_long=_finite("funding_rate_long", pair["funding_rate_long"]),
            funding_rate_short=_finite("funding_rate_short", pair["funding_rate_short"]),
            fee_bps_per_side=fee,
            slippage_bps_per_side=slip,
            gross_multiple=gross_multiple,
            position_open_at_settlement=position_open_at_settlement,
            fills_per_leg=fills_per_leg,
        )
        ledgers.append(
            {
                "asset_long": asset_long,
                "asset_short": asset_short,
                "notional_per_leg": notional_l,
                "ledger": ledger,
            }
        )

    total_net_pnl = sum(item["ledger"]["total_net_pnl"] for item in ledgers)
    total_funding = sum(item["ledger"]["funding_cash_flow"] for item in ledgers)
    total_fees = sum(item["ledger"]["fees"] for item in ledgers)
    total_slippage = sum(item["ledger"]["slippage"] for item in ledgers)
    total_price_basis_pnl = sum(item["ledger"]["net_price_basis_pnl"] for item in ledgers)

    return {
        "equity": equity_value,
        "gross_multiple": gross_multiple,
        "gross_exposure": gross_total,
        "gross_exposure_cap": gross_cap,
        "allocation": allocation,
        "notional_per_leg": notional_per_leg,
        "pairs": ledgers,
        "total_net_pnl": total_net_pnl,
        "total_funding_cash_flow": total_funding,
        "total_fees": total_fees,
        "total_slippage": total_slippage,
        "total_price_basis_pnl": total_price_basis_pnl,
        "signal_time": sig_t.isoformat().replace("+00:00", "Z"),
        "next_open_time": open_t.isoformat().replace("+00:00", "Z"),
    }
