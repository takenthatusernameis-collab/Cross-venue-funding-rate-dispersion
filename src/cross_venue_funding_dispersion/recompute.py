"""Deterministic independent recomputation verifier (standard library only).

The red-team audit requires that published metrics be independently recomputed
from immutable event-ledger rows and match within registered tolerances. This
module provides that primitive: it re-derives aggregate totals from the raw
per-configuration ledger rows stored in a run artifact and compares them to
the artifact's published aggregates. It performs no economic evaluation, makes
no performance claims, and performs no network calls.
"""
from __future__ import annotations

import math
from typing import Any


def _finite(name: str, value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def recompute_ledger_totals(records: list[dict[str, Any]]) -> dict[str, float]:
    """Independently sum aggregate fields from per-configuration ledger rows.

    Each record must expose the per-configuration totals produced by
    `run_configuration`. The recomputation sums the constituent parts across
    all records and returns the independent aggregates.
    """
    if not isinstance(records, list):
        raise ValueError("records must be a list")
    if not records:
        raise ValueError("records must be non-empty")
    totals: dict[str, float] = {
        "total_net_pnl": 0.0,
        "total_funding_cash_flow": 0.0,
        "total_fees": 0.0,
        "total_slippage": 0.0,
        "total_price_basis_pnl": 0.0,
        "gross_exposure": 0.0,
        "n_pairs": 0,
        "n_configs": 0,
    }
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("each record must be a dict")
        for key in (
            "total_net_pnl", "total_funding_cash_flow", "total_fees",
            "total_slippage", "total_price_basis_pnl", "gross_exposure",
        ):
            if key not in record:
                raise ValueError(f"record missing {key}")
            totals[key] += _finite(key, record[key])
        if "n_pairs" not in record:
            raise ValueError("record missing n_pairs")
        if not isinstance(record["n_pairs"], int) or isinstance(record["n_pairs"], bool) or record["n_pairs"] < 0:
            raise ValueError("n_pairs must be a non-negative integer")
        totals["n_pairs"] += record["n_pairs"]
        totals["n_configs"] += 1
    return totals


def verify_artifact_consistency(
    artifact: dict[str, Any],
    *,
    tolerance: float = 1e-9,
) -> dict[str, Any]:
    """Recompute artifact aggregates from ledger rows and compare to published.

    The artifact must expose a list of per-configuration records under
    `records` and published aggregate fields under `published`. Returns the
    recomputed totals, per-field absolute deltas and a pass/fail flag. Fails
    closed on malformed input.
    """
    if not isinstance(artifact, dict):
        raise ValueError("artifact must be a dict")
    if "records" not in artifact:
        raise ValueError("artifact missing records")
    if "published" not in artifact:
        raise ValueError("artifact missing published")
    records = artifact["records"]
    if not isinstance(records, list):
        raise ValueError("artifact records must be a list")
    if not records:
        raise ValueError("artifact records must be non-empty")
    published = artifact["published"]
    if not isinstance(published, dict):
        raise ValueError("artifact published must be a dict")
    if not math.isfinite(float(tolerance)) or float(tolerance) < 0:
        raise ValueError("tolerance must be finite and non-negative")

    recomputed = recompute_ledger_totals(records)
    deltas: dict[str, float] = {}
    mismatches: list[str] = []
    for key in (
        "total_net_pnl", "total_funding_cash_flow", "total_fees",
        "total_slippage", "total_price_basis_pnl", "gross_exposure",
        "n_pairs", "n_configs",
    ):
        if key not in published:
            raise ValueError(f"published missing {key}")
        pub = _finite(f"published.{key}", published[key])
        delta = abs(recomputed[key] - pub)
        deltas[key] = delta
        if delta > tolerance:
            mismatches.append(key)
    return {
        "recomputed": recomputed,
        "published": published,
        "deltas": deltas,
        "tolerance": float(tolerance),
        "mismatches": mismatches,
        "consistent": not mismatches,
    }


def attribution_check(
    artifact: dict[str, Any],
    *,
    tolerance: float = 1e-9,
) -> dict[str, Any]:
    """Verify the additive decomposition of total net PnL from its parts.

    Independent recomputation must confirm
    total_net_pnl == net_price_basis_pnl + funding - fees - slippage for the
    artifact's published aggregates. Fails closed on malformed input.
    """
    if not isinstance(artifact, dict):
        raise ValueError("artifact must be a dict")
    if "published" not in artifact:
        raise ValueError("artifact missing published")
    published = artifact["published"]
    if not isinstance(published, dict):
        raise ValueError("artifact published must be a dict")
    if not math.isfinite(float(tolerance)) or float(tolerance) < 0:
        raise ValueError("tolerance must be finite and non-negative")
    for key in (
        "total_net_pnl", "total_price_basis_pnl", "total_funding_cash_flow",
        "total_fees", "total_slippage",
    ):
        if key not in published:
            raise ValueError(f"published missing {key}")
    net = _finite("published.total_net_pnl", published["total_net_pnl"])
    basis = _finite("published.total_price_basis_pnl", published["total_price_basis_pnl"])
    funding = _finite("published.total_funding_cash_flow", published["total_funding_cash_flow"])
    fees = _finite("published.total_fees", published["total_fees"])
    slippage = _finite("published.total_slippage", published["total_slippage"])
    derived = basis + funding - fees - slippage
    delta = abs(net - derived)
    return {
        "published_total_net_pnl": net,
        "derived_total_net_pnl": derived,
        "delta": delta,
        "tolerance": float(tolerance),
        "consistent": delta <= tolerance,
    }