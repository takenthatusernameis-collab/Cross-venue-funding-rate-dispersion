#!/usr/bin/env python3
"""Independent, source-independent red-team audit of the FVD053 exploratory anchor ledger.

This auditor deliberately does NOT import `scripts/run_fvd053_anchor.py` or any
project module: it re-derives every arithmetic identity from the immutable
per-signal ledger rows so that a defect in the producer cannot be mirrored by a
defect in the checker. It recomputes, from the artifact alone:

- row/count invariants and the daily-selection additive partition;
- entry/exit UTC alignment and the frozen 24h holding period;
- per-signal price/basis PnL from raw leg prices and equal notionals;
- fees and slippage from the frozen bps assumptions;
- the per-signal identity net = price_basis + funding - fees - slippage;
- aggregate totals, turnover, gross exposure and the 1.0x cap;
- return identities and cost-sensitivity arithmetic;
- per-underlying counts and venue-pair membership.

It also records what the persisted ledger CANNOT prove (funding-rate rows,
dispersion/threshold series, source candles, contract identity), so no review
can mistake a green arithmetic check for an audited economic result.

Offline only: no network, no credentials, no trading, no frozen artifact writes.
"""
import argparse
import hashlib
import json
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT = ROOT / "research_state" / "fvd053_anchor_run_2026-11-21.json"
DEFAULT_MANIFEST = ROOT / "research_state" / "exploratory_run_manifest_2026-11-21.json"
TOLERANCE = 1e-6

UNVERIFIABLE_LIMITATIONS = [
    "No per-settlement funding rate rows are persisted, so funding cash-flow magnitude and sign cannot be recomputed from the ledger; only settlement counts and the funding term in the net identity are checkable.",
    "No daily dispersion series, threshold percentile values, or selected-taillist are persisted, so the top-10% selection and the prior-90-day 80th-percentile threshold cannot be independently recomputed offline.",
    "Entry/exit prices are not traceable to persisted raw venue candles or response hashes in this artifact, so price provenance cannot be re-verified from the ledger alone.",
    "Contract identity is underlying-symbol-mapped only (candidate level); lifecycle, multiplier and settlement-currency equivalence are unproven.",
    "The two venues settle funding on different cadences (Hyperliquid hourly, OKX 8-hourly), so 27 settlements per 24h hold is asserted as an invariant, not validated against raw rates.",
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_utc(text):
    if not isinstance(text, str):
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _is_num(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _close(a, b, tol=TOLERANCE) -> bool:
    return _is_num(a) and _is_num(b) and abs(a - b) <= tol


def _price_pnl(row, notional):
    long_pnl = notional * (row["exit_price_long"] / row["entry_price_long"] - 1.0)
    short_pnl = notional * (1.0 - row["exit_price_short"] / row["entry_price_short"])
    return long_pnl + short_pnl


def audit_ledger(doc: dict, manifest: dict | None = None, tolerance: float = TOLERANCE) -> dict:
    """Return deterministic audit findings for one anchor ledger document."""
    checks: list[dict] = []

    def record(check_id, passed, detail):
        checks.append({"check": check_id, "passed": bool(passed), "detail": detail})

    signals = doc.get("signals") or []
    params = doc.get("anchor_params") or {}
    equity = doc.get("equity")
    att = doc.get("attribution") or {}
    fee_bps = params.get("fee_bps_per_side")
    slip_bps = params.get("slippage_bps_per_side")
    holding = params.get("holding_hours")

    record(
        "document_status",
        doc.get("status") == "EXPLORATORY_ONLY"
        and doc.get("confirmatory_status_preserved") == "BLOCKED_DATA_GATE"
        and doc.get("backtest_completed") is False
        and doc.get("performance_metrics_computed") is False,
        {
            "status": doc.get("status"),
            "confirmatory_status_preserved": doc.get("confirmatory_status_preserved"),
            "backtest_completed": doc.get("backtest_completed"),
            "performance_metrics_computed": doc.get("performance_metrics_computed"),
        },
    )

    record(
        "row_count_invariants",
        len(signals) == doc.get("signal_count") == doc.get("dates_with_signal"),
        {"rows": len(signals), "signal_count": doc.get("signal_count"), "dates_with_signal": doc.get("dates_with_signal")},
    )

    record(
        "selection_partition",
        doc.get("dates_total") == doc.get("dates_with_signal", 0) + doc.get("dates_with_no_signal", 0)
        and doc.get("dates_with_no_signal")
        == doc.get("dates_threshold_ineligible", 0) + doc.get("dates_threshold_eligible_no_signal", 0),
        {
            "dates_total": doc.get("dates_total"),
            "dates_with_signal": doc.get("dates_with_signal"),
            "dates_with_no_signal": doc.get("dates_with_no_signal"),
            "dates_threshold_ineligible": doc.get("dates_threshold_ineligible"),
            "dates_threshold_eligible_no_signal": doc.get("dates_threshold_eligible_no_signal"),
        },
    )

    record(
        "no_skipped_rows",
        all(row.get("skipped") is False for row in signals),
        {"skipped": sum(1 for row in signals if row.get("skipped") is not False)},
    )

    timing_errors = []
    starts = _parse_utc(doc.get("window_start_utc"))
    fetch_end = _parse_utc(doc.get("fetch_end_utc"))
    for row in signals:
        entry = _parse_utc(row.get("entry_time_utc"))
        exit_ = _parse_utc(row.get("exit_time_utc"))
        if entry is None or exit_ is None:
            timing_errors.append(row.get("entry_time_utc"))
            continue
        if entry.minute or entry.second or exit_.minute or exit_.second:
            timing_errors.append(f"{row.get('entry_time_utc')} not hour-aligned")
        if _is_num(holding) and (exit_ - entry).total_seconds() != holding * 3600:
            timing_errors.append(f"{row.get('entry_time_utc')} holding != {holding}h")
        if starts and entry < starts:
            timing_errors.append(f"{row.get('entry_time_utc')} before window start")
        if fetch_end and exit_ > fetch_end:
            timing_errors.append(f"{row.get('exit_time_utc')} after fetch end")
    record("entry_exit_timing", not timing_errors, {"violations": timing_errors[:5], "count": len(timing_errors)})

    entry_dates = [row.get("entry_time_utc") for row in signals]
    record(
        "one_signal_per_date",
        len(entry_dates) == len(set(entry_dates)),
        {"unique_entry_times": len(set(entry_dates)), "rows": len(entry_dates)},
    )

    settlement_counts = sorted({row.get("funding_settlements") for row in signals})
    record(
        "funding_settlement_invariant",
        settlement_counts == [27]
        and sum(row.get("funding_settlements", 0) for row in signals) == doc.get("total_funding_settlements"),
        {"per_signal_settlements": settlement_counts, "total": doc.get("total_funding_settlements")},
    )

    exposure_errors = []
    for row in signals:
        notional = row.get("notional_per_leg")
        if not _is_num(notional) or not _close(notional, 5000.0):
            exposure_errors.append("notional_per_leg")
        if not _close(row.get("gross_exposure"), 2 * notional if _is_num(notional) else None):
            exposure_errors.append("gross_exposure != 2*notional")
        if _is_num(equity) and _is_num(params.get("gross_multiple")):
            if not _close(row.get("gross_exposure"), equity * params["gross_multiple"]):
                exposure_errors.append("gross_exposure != equity*gross_multiple")
    record("equal_notional_and_cap", not exposure_errors, {"violations": exposure_errors[:5], "count": len(exposure_errors)})

    price_errors = []
    fee_errors = []
    net_errors = []
    for row in signals:
        notional = row.get("notional_per_leg")
        if not _is_num(notional):
            price_errors.append("non-numeric notional")
            continue
        expected_price = _price_pnl(row, notional)
        if not _close(expected_price, row.get("price_basis_pnl"), tolerance):
            price_errors.append(f"{row.get('underlying')} {row.get('entry_time_utc')}: {expected_price} vs {row.get('price_basis_pnl')}")
        expected_fee = 4.0 * notional * fee_bps / 1e4
        expected_slip = 4.0 * notional * slip_bps / 1e4
        if not (_close(row.get("fees"), expected_fee) and _close(row.get("slippage"), expected_slip)):
            fee_errors.append(f"{row.get('underlying')} {row.get('entry_time_utc')}")
        expected_net = row.get("price_basis_pnl") + row.get("funding_cash_flow") - row.get("fees") - row.get("slippage")
        if not _close(expected_net, row.get("net_pnl"), tolerance):
            net_errors.append(f"{row.get('underlying')} {row.get('entry_time_utc')}")
    record("price_basis_pnl_recomputed", not price_errors, {"violations": price_errors[:5], "count": len(price_errors)})
    record("fees_and_slippage_recomputed", not fee_errors, {"violations": fee_errors[:5], "count": len(fee_errors)})
    record("per_signal_net_identity", not net_errors, {"violations": net_errors[:5], "count": len(net_errors)})

    sums = {
        "total_fees": sum(row.get("fees", 0) for row in signals),
        "total_slippage": sum(row.get("slippage", 0) for row in signals),
        "total_funding_cash_flow": sum(row.get("funding_cash_flow", 0) for row in signals),
        "total_price_basis_pnl": sum(row.get("price_basis_pnl", 0) for row in signals),
        "total_net_pnl": sum(row.get("net_pnl", 0) for row in signals),
    }
    record(
        "aggregate_totals",
        all(_close(sums[k], att.get(k), tolerance) for k in sums),
        {k: {"recomputed": sums[k], "recorded": att.get(k)} for k in sums},
    )

    expected_turnover = sum(4.0 * row.get("notional_per_leg", 0.0) for row in signals)
    record(
        "turnover_recomputed",
        _close(expected_turnover, doc.get("turnover_notional")),
        {"recomputed": expected_turnover, "recorded": doc.get("turnover_notional")},
    )

    expected_exposure = sum(row.get("gross_exposure", 0.0) for row in signals) / len(signals) if signals else None
    record(
        "average_gross_exposure_recomputed",
        _close(expected_exposure, doc.get("average_gross_exposure")),
        {"recomputed": expected_exposure, "recorded": doc.get("average_gross_exposure")},
    )

    expected_net_return = sums["total_net_pnl"] / equity if _is_num(equity) else None
    expected_price_return = sums["total_price_basis_pnl"] / equity if _is_num(equity) else None
    record(
        "return_identities",
        _close(expected_net_return, doc.get("net_return"), 1e-12)
        and _close(expected_price_return, doc.get("gross_price_return"), 1e-12)
        and _close(abs(expected_net_return), doc.get("peak_to_trough_decline"), 1e-12),
        {
            "net_return": {"recomputed": expected_net_return, "recorded": doc.get("net_return")},
            "gross_price_return": {"recomputed": expected_price_return, "recorded": doc.get("gross_price_return")},
            "peak_to_trough_decline": {
                "recomputed_abs": abs(expected_net_return) if _is_num(expected_net_return) else None,
                "recorded": doc.get("peak_to_trough_decline"),
            },
        },
    )

    sensitivity = doc.get("cost_sensitivity") or {}
    base_ret = doc.get("net_return")
    saved = sum(
        4.0 * row.get("notional_per_leg", 0.0) * (fee_bps + slip_bps - 2.0 * bps) / 1e4
        for row in signals
        for bps in [sensitivity.get("optimistic_fee_slippage_bps", [None])[0]]
        if _is_num(bps)
    )
    extra = sum(
        4.0 * row.get("notional_per_leg", 0.0) * (2.0 * bps - (fee_bps + slip_bps)) / 1e4
        for row in signals
        for bps in [sensitivity.get("stress_fee_slippage_bps", [None])[0]]
        if _is_num(bps)
    )
    record(
        "cost_sensitivity_arithmetic",
        _close(base_ret, sensitivity.get("base_net_return"), 1e-12)
        and _close(base_ret + saved / equity, sensitivity.get("optimistic_net_return"), 1e-12)
        and _close(base_ret - extra / equity, sensitivity.get("stress_net_return"), 1e-12),
        {
            "base": {"recomputed": base_ret, "recorded": sensitivity.get("base_net_return")},
            "optimistic": {
                "recomputed": base_ret + saved / equity if _is_num(base_ret) and _is_num(equity) else None,
                "recorded": sensitivity.get("optimistic_net_return"),
            },
            "stress": {
                "recomputed": base_ret - extra / equity if _is_num(base_ret) and _is_num(equity) else None,
                "recorded": sensitivity.get("stress_net_return"),
            },
        },
    )

    returns = [row.get("net_return") for row in signals]
    expected_vol = statistics.stdev(returns) if len(returns) > 1 else None
    record(
        "per_signal_volatility_definition",
        _close(expected_vol, doc.get("volatility_per_signal_return"), 1e-12),
        {"recomputed_sample_stdev": expected_vol, "recorded": doc.get("volatility_per_signal_return")},
    )

    per_underlying = {}
    for row in signals:
        per_underlying[row.get("underlying")] = per_underlying.get(row.get("underlying"), 0) + 1
    record(
        "per_underlying_counts",
        per_underlying == (manifest or {}).get("coverage_summary", {}).get("underlyings_with_signals", per_underlying),
        {"recomputed": per_underlying, "manifest": (manifest or {}).get("coverage_summary", {}).get("underlyings_with_signals")},
    )

    allowed_pairs = {tuple(pair) for pair in doc.get("venue_pairs") or []}
    bad_pairs = [
        [row.get("underlying"), row.get("long_venue"), row.get("short_venue")]
        for row in signals
        if (row.get("underlying"), row.get("long_venue"), row.get("short_venue")) not in allowed_pairs
    ]
    record(
        "venue_pair_membership",
        not bad_pairs and all(row.get("long_venue") in (doc.get("venues") or []) for row in signals),
        {"violations": bad_pairs[:5], "count": len(bad_pairs), "venues": doc.get("venues")},
    )

    peak_pct = doc.get("peak_to_trough_decline_pct_of_equity")
    expected_pct = abs(expected_net_return) * 100.0 if _is_num(expected_net_return) else None
    label_defects = []
    if not _close(peak_pct, expected_pct, 1e-9):
        label_defects.append(
            {
                "field": "peak_to_trough_decline_pct_of_equity",
                "recorded": peak_pct,
                "expected_percent_of_equity": expected_pct,
                "severity": "derived_label_units",
                "note": "recorded value is scaled by ~1e-4 relative to a percent-of-equity label; flagged here, not rewritten in the immutable ledger",
            }
        )

    failed = [check["check"] for check in checks if not check["passed"]]
    return {
        "schema_version": "1.0",
        "audit_type": "independent_fvd053_anchor_ledger_recomputation",
        "auditor": "scripts/audit_fvd053_anchor.py (no import of scripts/run_fvd053_anchor.py)",
        "tolerance_abs": tolerance,
        "checks": checks,
        "passed_checks": len(checks) - len(failed),
        "failed_checks": failed,
        "label_defects": label_defects,
        "verdict": "PASS" if not failed else "MISMATCH",
        "limitations": UNVERIFIABLE_LIMITATIONS,
    }


def audit_files(artifact_path: Path, manifest_path: Path | None) -> dict:
    doc = json.loads(artifact_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path and manifest_path.is_file() else None
    result = audit_ledger(doc, manifest)
    result["target_artifact"] = str(artifact_path.relative_to(ROOT)) if artifact_path.is_relative_to(ROOT) else str(artifact_path)
    result["target_sha256"] = sha256_file(artifact_path)
    result["target_experiment_id"] = doc.get("experiment_id")
    result["target_observed_at_utc"] = doc.get("observed_at_utc")
    if manifest is not None:
        recorded = {
            Path(entry.get("path", "")).name: entry.get("sha256")
            for entry in manifest.get("output_artifacts", [])
            if isinstance(entry, dict)
        }
        digest = recorded.get(artifact_path.name)
        result["manifest_sha256_match"] = digest == result["target_sha256"]
        if digest != result["target_sha256"]:
            result["failed_checks"] = result["failed_checks"] + ["manifest_sha256_match"]
            result["verdict"] = "MISMATCH"
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Independently recompute the FVD053 anchor ledger identities.")
    parser.add_argument("--artifact", default=str(DEFAULT_ARTIFACT))
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--output", default=None, help="Write the audit record JSON to this path.")
    args = parser.parse_args(argv)

    artifact = Path(args.artifact)
    if not artifact.is_absolute():
        artifact = ROOT / artifact
    manifest = Path(args.manifest)
    if not manifest.is_absolute():
        manifest = ROOT / manifest

    result = audit_files(artifact, manifest if manifest.is_file() else None)

    if args.output:
        output = Path(args.output)
        if not output.is_absolute():
            output = ROOT / output
        result["recomputed_at_utc"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        result["performance_metrics_computed"] = False
        result["economic_claim"] = "none: arithmetic/identity audit of descriptive exploratory accounting only"
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if result["verdict"] == "PASS":
        print(
            f"FVD053_ANCHOR_AUDIT=PASS checks={len(result['checks'])} failed=0 "
            f"label_defects={len(result.get('label_defects') or [])}"
        )
        return 0
    print(f"FVD053_ANCHOR_AUDIT=MISMATCH failed={result['failed_checks']}")
    for check in result["checks"]:
        if not check["passed"]:
            print(f"- {check['check']}: {json.dumps(check['detail'], sort_keys=True)[:400]}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
