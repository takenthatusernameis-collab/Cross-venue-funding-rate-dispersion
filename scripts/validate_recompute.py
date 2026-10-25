#!/usr/bin/env python3
"""Offline conformance check for recompute/determinism (standard library only)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.recompute import (
    attribution_check,
    recompute_ledger_totals,
    verify_artifact_consistency,
)


def validate_recompute() -> list[str]:
    errors = []
    records = [
        {
            "total_net_pnl": 10.0,
            "total_funding_cash_flow": 2.0,
            "total_fees": 1.0,
            "total_slippage": 0.5,
            "total_price_basis_pnl": 9.5,
            "gross_exposure": 100.0,
            "n_pairs": 1,
        },
        {
            "total_net_pnl": -6.0,
            "total_funding_cash_flow": -1.0,
            "total_fees": 0.5,
            "total_slippage": 0.5,
            "total_price_basis_pnl": -4.0,
            "gross_exposure": 100.0,
            "n_pairs": 1,
        },
    ]
    totals = recompute_ledger_totals(records)
    if totals["total_net_pnl"] != 4.0:
        errors.append("recomputed net pnl wrong")
    if totals["total_funding_cash_flow"] != 1.0:
        errors.append("recomputed funding wrong")
    if totals["n_configs"] != 2:
        errors.append("config count wrong")
    if totals["n_pairs"] != 2:
        errors.append("pair count wrong")
    # verify_artifact_consistency passes when published matches recomputed.
    published = {
        "total_net_pnl": 4.0,
        "total_funding_cash_flow": 1.0,
        "total_fees": 1.5,
        "total_slippage": 1.0,
        "total_price_basis_pnl": 5.5,
        "gross_exposure": 200.0,
        "n_pairs": 2,
        "n_configs": 2,
    }
    artifact = {"records": records, "published": published}
    result = verify_artifact_consistency(artifact)
    if not result["consistent"]:
        errors.append("consistent artifact reported inconsistent")
    if abs(result["deltas"]["total_net_pnl"]) > 1e-9:
        errors.append("recompute delta nonzero")
    # attribution_check verifies the additive decomposition.
    att = attribution_check(artifact)
    if not att["consistent"]:
        errors.append("attribution decomposition inconsistent")
    if abs(att["delta"]) > 1e-9:
        errors.append("attribution delta wrong")
    # Fail-closed: mismatched published totals are detected.
    bad = {"records": records, "published": dict(published, total_net_pnl=999.0)}
    result_bad = verify_artifact_consistency(bad)
    if result_bad["consistent"]:
        errors.append("mismatched artifact reported consistent")
    # Empty records fail closed.
    try:
        recompute_ledger_totals([])
        errors.append("empty records accepted")
    except ValueError:
        pass
    except Exception as exc:
        errors.append(f"empty records raised wrong type: {exc}")
    # Malformed artifact fails closed.
    try:
        verify_artifact_consistency({"records": records})
        errors.append("missing published accepted")
    except ValueError:
        pass
    except Exception as exc:
        errors.append(f"missing published raised wrong type: {exc}")
    return errors


def main() -> int:
    errors = validate_recompute()
    if errors:
        for e in errors:
            print("FAIL:", e)
        sys.exit(1)
    print("RECOMPUTE_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
