import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_blocked_manifest_claims import validate_manifest, main as blocked_main  # noqa: E402
from validate_no_performance_claims import scan_text, scan_path, main as no_perf_main  # noqa: E402

BASE_BLOCKED = {
    "schema_version": "1.0",
    "experiment_id": "FVD-DISPERSION-V1",
    "run_id": "run-2026-01-01",
    "status": "BLOCKED_DATA_GATE",
    "backtest_completed": False,
    "performance_metrics_computed": False,
    "historical_point_in_time_market_cap_gate": "BLOCKED",
    "output_artifacts": [],
    "caveats": ["no performance claim"],
}


class BlockedManifestClaimsTests(unittest.TestCase):
    def test_blocked_manifest_without_claims_passes(self):
        validate_manifest(dict(BASE_BLOCKED), "run_manifest.json")

    def test_not_run_manifest_without_claims_passes(self):
        validate_manifest(dict(BASE_BLOCKED, status="NOT_RUN"), "run_manifest.json")

    def test_exploratory_manifest_without_claims_passes(self):
        validate_manifest(dict(BASE_BLOCKED, status="EXPLORATORY_ONLY"),
                            "exploratory_run_manifest_2026-10-24.json")

    def test_inconclusive_manifest_without_claims_passes(self):
        validate_manifest(dict(BASE_BLOCKED, status="INCONCLUSIVE"),
                            "exploratory_run_manifest_2026-10-24.json")

    def test_blocked_backtest_completed_true_fails(self):
        with self.assertRaises(SystemExit):
            validate_manifest(dict(BASE_BLOCKED, backtest_completed=True), "run_manifest.json")

    def test_blocked_performance_metrics_computed_true_fails(self):
        with self.assertRaises(SystemExit):
            validate_manifest(dict(BASE_BLOCKED, performance_metrics_computed=True),
                              "run_manifest.json")

    def test_blocked_sharpe_key_fails(self):
        with self.assertRaises(SystemExit):
            validate_manifest(dict(BASE_BLOCKED, sharpe=1.5), "run_manifest.json")

    def test_blocked_max_drawdown_key_fails(self):
        with self.assertRaises(SystemExit):
            validate_manifest(dict(BASE_BLOCKED, max_drawdown=0.2), "run_manifest.json")

    def test_blocked_equity_curve_key_fails(self):
        with self.assertRaises(SystemExit):
            validate_manifest(dict(BASE_BLOCKED, equity_curve=[]), "run_manifest.json")

    def test_exploratory_annualized_return_key_fails(self):
        with self.assertRaises(SystemExit):
            validate_manifest(dict(BASE_BLOCKED, status="EXPLORATORY_ONLY", annualized_return=0.1),
                              "exploratory_run_manifest_2026-10-24.json")

    def test_exploratory_backtest_completed_true_fails(self):
        with self.assertRaises(SystemExit):
            validate_manifest(dict(BASE_BLOCKED, status="EXPLORATORY_ONLY", backtest_completed=True),
                              "exploratory_run_manifest_2026-10-24.json")

    def test_unknown_status_is_permissive(self):
        validate_manifest(dict(BASE_BLOCKED, status="COMPLETED"), "run_manifest.json")

    def test_committed_blocked_manifests_pass_integration(self):
        self.assertEqual(blocked_main(None), 0)


class NoPerformanceClaimsTests(unittest.TestCase):
    def test_clean_markdown_passes(self):
        scan_text("# Heading\nOrdinary research setup text.\n", "README.md")

    def test_clean_json_passes(self):
        scan_text(json.dumps({"status": "BLOCKED_DATA_GATE", "backtest_completed": False}),
                  "run_manifest.json")

    def test_forbidden_token_in_markdown_fails(self):
        with self.assertRaises(SystemExit):
            scan_text("The sharpe ratio was positive.", "HANDOFF.md")

    def test_forbidden_token_in_json_fails(self):
        with self.assertRaises(SystemExit):
            scan_text(json.dumps({"pnl_total": 100}), "research_state/x.json")

    def test_case_insensitive(self):
        with self.assertRaises(SystemExit):
            scan_text("Sharpe Ratio", "x.md")

    def test_multiple_forbidden_tokens(self):
        with self.assertRaises(SystemExit):
            scan_text("calmar and sortino", "x.md")

    def test_committed_targets_pass_integration(self):
        self.assertEqual(no_perf_main(None), 0)


if __name__ == "__main__":
    unittest.main()
