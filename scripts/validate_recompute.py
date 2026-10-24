"""Offline conformance check for the independent recomputation verifier.

Standard library only; no network calls; no economic result.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from cross_venue_funding_dispersion.recompute import (
    attribution_check,
    recompute_ledger_totals,
    verify_artifact_consistency,
)


def check(cond, msg):
    if not cond:
        print("FAIL:", msg)
        sys.exit(1)


def _record(net=1.0, funding=0.1, fees=0.05, slippage=0.02, basis=0.9, gross=100.0, n_pairs=1):
    return {
        "total_net_pnl": net,
        "total_funding_cash_flow": funding,
        "total_fees": fees,
        "total_slippage": slippage,
        "total_price_basis_pnl": basis,
        "gross_exposure": gross,
        "n_pairs": n_pairs,
    }


def main():
    # Independent recomputation from ledger rows matches published aggregates.
    records = [
        _record(net=1.0, basis=0.9, n_pairs=1, gross=100.0),
        _record(net=2.0, basis=1.8, n_pairs=2, gross=100.0),
    ]
    published = recompute_ledger_totals(records)
    artifact = {"records": records, "published": published}
    result = verify_artifact_consistency(artifact)
    check(result["consistent"], "artifact consistency")
    check(result["recomputed"]["n_configs"] == 2, "n_configs")
    check(result["recomputed"]["n_pairs"] == 3, "n_pairs")
    check(result["recomputed"]["total_net_pnl"] == 3.0, "total_net_pnl sum")
    check(result["recomputed"]["gross_exposure"] == 200.0, "gross exposure sum")

    # Additive attribution decomposition.
    attr = attribution_check(artifact)
    check(attr["consistent"], "attribution decomposition")
    check(abs(attr["derived_total_net_pnl"] - 3.0) < 1e-12, "derived total net pnl")

    # Mismatch detection.
    bad = {"records": records, "published": dict(published, total_net_pnl=99.0)}
    check(not verify_artifact_consistency(bad)["consistent"], "mismatch detected")
    check(not attribution_check(bad)["consistent"], "attribution mismatch detected")

    # Fail-closed on malformed artifacts.
    for malformed in [
        {},
        {"records": records},
        {"published": published},
        {"records": "x", "published": published},
        {"records": [], "published": published},
        {"records": records, "published": "x"},
        {"records": records, "published": {}},
    ]:
        try:
            verify_artifact_consistency(malformed)
            check(False, "malformed artifact accepted")
        except ValueError:
            pass

    # Fail-closed on bad tolerance.
    for bad_tol in (float("nan"), -1.0):
        try:
            verify_artifact_consistency(artifact, tolerance=bad_tol)
            check(False, "bad tolerance accepted")
        except ValueError:
            pass

    print("RECOMPUTE_VALIDATION=PASS")


if __name__ == "__main__":
    main()