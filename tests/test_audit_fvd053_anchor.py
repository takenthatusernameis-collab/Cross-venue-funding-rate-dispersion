"""Offline tests for scripts/audit_fvd053_anchor.py.

The auditor must be a genuine independent checker: these tests prove it
reproduces a known-answer synthetic ledger, and that it FAILS when any
per-signal identity, aggregate, timing, exposure or selection invariant is
tampered with. No network, no producer import.
"""
import copy
import json
import statistics
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import audit_fvd053_anchor as auditor


def build_ledger():
    rows = []
    prices = [
        ("ETH", "OKX", "Hyperliquid", 100.0, 101.0, 100.5, 100.6, 1.5),
        ("AVAX", "OKX", "Hyperliquid", 20.0, 19.5, 20.05, 19.55, -0.5),
    ]
    for idx, (under, long_v, short_v, el, xl, es, xs, funding) in enumerate(prices):
        notional = 5000.0
        price_pnl = notional * (xl / el - 1.0) + notional * (1.0 - xs / es)
        fees = 4.0 * notional * 5.0 / 1e4
        slippage = 4.0 * notional * 5.0 / 1e4
        net = price_pnl + funding - fees - slippage
        rows.append(
            {
                "underlying": under,
                "long_venue": long_v,
                "short_venue": short_v,
                "entry_time_utc": f"2026-09-{20 + idx:02d}T23:00:00Z",
                "exit_time_utc": f"2026-09-{21 + idx:02d}T23:00:00Z",
                "entry_price_long": el,
                "exit_price_long": xl,
                "entry_price_short": es,
                "exit_price_short": xs,
                "notional_per_leg": notional,
                "gross_exposure": 2 * notional,
                "funding_settlements": 27,
                "funding_cash_flow": funding,
                "price_basis_pnl": price_pnl,
                "fees": fees,
                "slippage": slippage,
                "net_pnl": net,
                "net_return": net / 10000.0,
                "skipped": False,
            }
        )
    total_net = sum(r["net_pnl"] for r in rows)
    base_ret = total_net / 10000.0
    saved = sum(4.0 * r["notional_per_leg"] * (5.0 + 5.0 - 2.0 * 2.0) / 1e4 for r in rows)
    extra = sum(4.0 * r["notional_per_leg"] * (2.0 * 10.0 - (5.0 + 5.0)) / 1e4 for r in rows)
    return {
        "schema_version": "1.0",
        "experiment_id": "FVD-EXPLORATORY-TEST",
        "status": "EXPLORATORY_ONLY",
        "confirmatory_status_preserved": "BLOCKED_DATA_GATE",
        "backtest_completed": False,
        "performance_metrics_computed": False,
        "anchor_params": {
            "holding_hours": 24,
            "fee_bps_per_side": 5.0,
            "slippage_bps_per_side": 5.0,
            "gross_multiple": 1.0,
        },
        "equity": 10000.0,
        "window_start_utc": "2026-07-20T00:00:00Z",
        "fetch_end_utc": "2026-10-26T16:00:00Z",
        "dates_total": 97,
        "dates_with_signal": len(rows),
        "dates_with_no_signal": 97 - len(rows),
        "dates_threshold_ineligible": 61,
        "dates_threshold_eligible_no_signal": 97 - len(rows) - 61,
        "signal_count": len(rows),
        "signals": rows,
        "total_funding_settlements": 27 * len(rows),
        "turnover_notional": sum(4.0 * r["notional_per_leg"] for r in rows),
        "average_gross_exposure": sum(r["gross_exposure"] for r in rows) / len(rows),
        "net_return": base_ret,
        "gross_price_return": sum(r["price_basis_pnl"] for r in rows) / 10000.0,
        "peak_to_trough_decline": abs(base_ret),
        "peak_to_trough_decline_pct_of_equity": abs(base_ret) * 1e-4,
        "volatility_per_signal_return": statistics.stdev([r["net_return"] for r in rows]),
        "cost_sensitivity": {
            "base_fee_slippage_bps": [5.0, 5.0],
            "base_net_return": base_ret,
            "optimistic_fee_slippage_bps": [2.0, 2.0],
            "optimistic_net_return": base_ret + saved / 10000.0,
            "stress_fee_slippage_bps": [10.0, 10.0],
            "stress_net_return": base_ret - extra / 10000.0,
        },
        "attribution": {
            "total_fees": sum(r["fees"] for r in rows),
            "total_slippage": sum(r["slippage"] for r in rows),
            "total_funding_cash_flow": sum(r["funding_cash_flow"] for r in rows),
            "total_price_basis_pnl": sum(r["price_basis_pnl"] for r in rows),
            "total_net_pnl": total_net,
        },
        "venue_pairs": [
            ["ETH", "OKX", "Hyperliquid"],
            ["AVAX", "OKX", "Hyperliquid"],
        ],
        "venues": ["Hyperliquid", "OKX"],
        "_underlyings": {"ETH": 1, "AVAX": 1},
    }


def manifest_for(ledger):
    return {
        "coverage_summary": {
            "underlyings_with_signals": {"ETH": 1, "AVAX": 1},
        }
    }


class AuditorKnownAnswerTests(unittest.TestCase):
    def test_known_answer_ledger_passes_all_identities(self):
        ledger = build_ledger()
        result = auditor.audit_ledger(ledger, manifest_for(ledger))
        self.assertEqual(result["failed_checks"], [], result["failed_checks"])
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(len(result["checks"]), result["passed_checks"])

    def test_label_unit_defect_is_flagged_but_does_not_mask_identity_pass(self):
        ledger = build_ledger()
        result = auditor.audit_ledger(ledger, manifest_for(ledger))
        self.assertEqual(result["verdict"], "PASS")
        self.assertEqual(len(result["label_defects"]), 1)
        self.assertEqual(result["label_defects"][0]["field"], "peak_to_trough_decline_pct_of_equity")


class AuditorAdversarialTests(unittest.TestCase):
    def assert_fails(self, ledger, check_name, manifest=None):
        result = auditor.audit_ledger(ledger, manifest if manifest is not None else manifest_for(ledger))
        self.assertIn(check_name, result["failed_checks"], result["failed_checks"])
        self.assertEqual(result["verdict"], "MISMATCH")

    def test_detects_tampered_price_pnl(self):
        ledger = build_ledger()
        ledger["signals"][0]["price_basis_pnl"] += 1.0
        auditor_result = auditor.audit_ledger(ledger, manifest_for(ledger))
        self.assertIn("price_basis_pnl_recomputed", auditor_result["failed_checks"])
        self.assertIn("aggregate_totals", auditor_result["failed_checks"])

    def test_detects_tampered_net_pnl(self):
        ledger = build_ledger()
        ledger["signals"][1]["net_pnl"] -= 0.01
        self.assert_fails(ledger, "per_signal_net_identity")

    def test_detects_broken_fee_assumption(self):
        ledger = build_ledger()
        ledger["signals"][0]["fees"] = 0.0
        self.assert_fails(ledger, "fees_and_slippage_recomputed")

    def test_detects_exposure_cap_breach(self):
        ledger = build_ledger()
        ledger["signals"][0]["gross_exposure"] = 20000.0
        self.assert_fails(ledger, "equal_notional_and_cap")

    def test_detects_wrong_holding_period(self):
        ledger = build_ledger()
        ledger["signals"][0]["exit_time_utc"] = "2026-09-21T22:00:00Z"
        self.assert_fails(ledger, "entry_exit_timing")

    def test_detects_selection_partition_break(self):
        ledger = build_ledger()
        ledger["dates_with_no_signal"] = 90
        self.assert_fails(ledger, "selection_partition")

    def test_detects_duplicate_signal_date(self):
        ledger = build_ledger()
        ledger["signals"][1]["entry_time_utc"] = ledger["signals"][0]["entry_time_utc"]
        self.assert_fails(ledger, "one_signal_per_date")

    def test_detects_unknown_venue_pair(self):
        ledger = build_ledger()
        ledger["signals"][0]["short_venue"] = "Binance"
        self.assert_fails(ledger, "venue_pair_membership")

    def test_detects_manifest_totals_mismatch(self):
        ledger = build_ledger()
        bad_manifest = {"coverage_summary": {"underlyings_with_signals": {"ETH": 2}}}
        self.assert_fails(ledger, "per_underlying_counts", manifest=bad_manifest)

    def test_detects_status_overclaim(self):
        ledger = build_ledger()
        ledger["performance_metrics_computed"] = True
        self.assert_fails(ledger, "document_status")

    def test_tampering_is_not_silently_accepted(self):
        ledger = build_ledger()
        broken = copy.deepcopy(ledger)
        broken["attribution"]["total_net_pnl"] += 5.0
        self.assert_fails(broken, "aggregate_totals")
        # the original remains auditable and passing
        clean = auditor.audit_ledger(ledger, manifest_for(ledger))
        self.assertNotIn("aggregate_totals", clean["failed_checks"])


class AuditorScriptContractTests(unittest.TestCase):
    def test_default_run_is_offline_and_does_not_import_producer(self):
        self.assertNotIn("run_fvd053_anchor", sys.modules)
        self.assertFalse(hasattr(auditor, "run_fvd053_anchor"))

    def test_artifact_is_valid_json_shape(self):
        ledger = build_ledger()
        json.dumps(ledger)
        self.assertEqual(ledger["anchor_params"]["holding_hours"], 24)
