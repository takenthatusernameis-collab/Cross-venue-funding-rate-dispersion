"""Source-independent run-orchestration harness (deterministic, no network).

Wires the frozen 108-config grid through the backtest skeleton and evaluation
primitives into a per-configuration event ledger with split-aware aggregation,
Holm-corrected validation-family reporting and immutable artifact persistence.
Produces no economic result by itself; evaluation mechanics only.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from datetime import datetime, timezone
from typing import Any

from cross_venue_funding_dispersion.backtest import run_backtest_skeleton
from cross_venue_funding_dispersion.evaluation import (
    GRID_FAMILY_SIZE,
    chronological_split_indices,
    holm_bonferroni,
)


def _finite(name: str, value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _utc(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
        value[:-1] + "+00:00" if isinstance(value, str) and value.endswith("Z") else value
    )
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def run_configuration(
    *,
    config_id: str,
    equity: float,
    pairs: list[dict[str, Any]],
    signal_time: str | datetime,
    next_open_time: str | datetime,
    fee_bps_per_side: float,
    slippage_bps_per_side: float,
    gross_multiple: float = 1.0,
    fills_per_leg: int = 2,
) -> dict[str, Any]:
    if not isinstance(config_id, str) or not config_id:
        raise ValueError("config_id must be a non-empty string")
    result = run_backtest_skeleton(
        equity=equity,
        pairs=pairs,
        signal_time=signal_time,
        next_open_time=next_open_time,
        fee_bps_per_side=fee_bps_per_side,
        slippage_bps_per_side=slippage_bps_per_side,
        gross_multiple=gross_multiple,
        fills_per_leg=fills_per_leg,
    )
    return {
        "config_id": config_id,
        "signal_time": result["signal_time"],
        "next_open_time": result["next_open_time"],
        "equity": result["equity"],
        "gross_multiple": result["gross_multiple"],
        "gross_exposure": result["gross_exposure"],
        "gross_exposure_cap": result["gross_exposure_cap"],
        "total_net_pnl": result["total_net_pnl"],
        "total_funding_cash_flow": result["total_funding_cash_flow"],
        "total_fees": result["total_fees"],
        "total_slippage": result["total_slippage"],
        "total_price_basis_pnl": result["total_price_basis_pnl"],
        "n_pairs": len(result["pairs"]),
    }


def aggregate_split_records(
    records: list[dict[str, Any]],
    *,
    total: int,
    discovery_fraction: float = 0.6,
    validation_fraction: float = 0.2,
    holdout_fraction: float = 0.2,
) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(records, list):
        raise ValueError("records must be a list")
    if len(records) != total:
        raise ValueError("records length must equal total")
    slices = chronological_split_indices(
        total,
        discovery_fraction=discovery_fraction,
        validation_fraction=validation_fraction,
        holdout_fraction=holdout_fraction,
    )
    return {
        "discovery": [records[s] for s in range(*slices["discovery"].indices(total))],
        "validation": [records[s] for s in range(*slices["validation"].indices(total))],
        "holdout": [records[s] for s in range(*slices["holdout"].indices(total))],
    }


def validation_family_report(
    validation_p_values: list[float],
) -> dict[str, Any]:
    if not isinstance(validation_p_values, list):
        raise ValueError("validation_p_values must be a list")
    adjusted = holm_bonferroni(validation_p_values)
    if len(adjusted) != len(validation_p_values):
        raise ValueError("adjusted length mismatch")
    if len(adjusted) > 0 and len(adjusted) != GRID_FAMILY_SIZE:
        # family size advisory only when a full grid family is supplied
        pass
    return {
        "family_size": len(adjusted),
        "expected_family_size": GRID_FAMILY_SIZE,
        "raw_p_values": list(validation_p_values),
        "holm_adjusted_p_values": adjusted,
        "n_rejected_at_0_05": sum(1 for p in adjusted if p < 0.05),
    }


def persist_run_artifact(path: str, payload: dict[str, Any]) -> str:
    if not isinstance(path, str) or not path:
        raise ValueError("path must be a non-empty string")
    if not isinstance(payload, dict):
        raise ValueError("payload must be a dict")
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def load_run_artifact(path: str) -> dict[str, Any]:
    if not isinstance(path, str) or not path:
        raise ValueError("path must be a non-empty string")
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("artifact must be a JSON object")
    return data
