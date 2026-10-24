"""Deterministic equal-notional pair allocation with a hard gross-exposure cap."""
from __future__ import annotations
import math


def allocate_equal_notional_pairs(equity: float, asset_ids: list[str], *, gross_multiple: float = 1.0) -> dict[str, float]:
    """Return notional per leg per asset; total gross across both legs <= equity*gross_multiple."""
    equity_value, multiple = float(equity), float(gross_multiple)
    if not math.isfinite(equity_value) or equity_value < 0:
        raise ValueError("equity must be finite and non-negative")
    if not math.isfinite(multiple) or not 0 <= multiple <= 1.0:
        raise ValueError("gross_multiple must be in [0, 1.0]")
    if len(set(asset_ids)) != len(asset_ids):
        raise ValueError("asset_ids must be unique")
    ordered = sorted(asset_ids)
    if not ordered or equity_value == 0 or multiple == 0:
        return {}
    notional_per_leg = equity_value * multiple / (2.0 * len(ordered))
    return {asset: notional_per_leg for asset in ordered}
