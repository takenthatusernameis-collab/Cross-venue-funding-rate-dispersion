import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_blocked_manifest_claims import (  # noqa: E402
    PERFORMANCE_KEYS,
    validate_manifest,
    main as blocked_main,
)

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

COMMITTED_MANIFESTS = [
    ROOT / "research_state/run_manifest.json",
    ROOT / "research_state/exploratory_run_manifest_2026-10-24.json",
    ROOT / "research_state/exploratory_run_manifest_2026-10-25.json",
]


def _temp_manifest(data):
    fd, path = tempfile.mkstemp(suffix=".json", prefix="blocked_claims_test_")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
    return Path(path)


class BlockedManifestClaimsTests(unittest.TestCase):
    def setUp(self):
        self.temp_paths = []

    def tearDown(self):
        for path in self.temp_paths:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _temp(self, data):
        path = _temp_manifest(data)
        self.temp_paths.append(path)
        return path

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

    def test_exploratory_backtest_completed_true_fails(self):
        with self.assertRaises(SystemExit):
            validate_manifest(dict(BASE_BLOCKED, status="EXPLORATORY_ONLY", backtest_completed=True),
                              "exploratory_run_manifest_2026-10-24.json")

    def test_exploratory_performance_metrics_computed_true_fails(self):
        with self.assertRaises(SystemExit):
            validate_manifest(dict(BASE_BLOCKED, status="EXPLORATORY_ONLY", performance_metrics_computed=True),
                              "exploratory_run_manifest_2026-10-24.json")

    def test_every_blocked_performance_key_fails(self):
        for key in PERFORMANCE_KEYS:
            with self.subTest(key=key):
                with self.assertRaises(SystemExit):
                    validate_manifest(dict(BASE_BLOCKED, **{key: 1.0}), "run_manifest.json")

    def test_every_exploratory_performance_key_fails(self):
        for key in PERFORMANCE_KEYS:
            with self.subTest(key=key):
                with self.assertRaises(SystemExit):
                    validate_manifest(dict(BASE_BLOCKED, status="EXPLORATORY_ONLY", **{key: 1.0}),
                                      "exploratory_run_manifest_2026-10-24.json")

    def test_committed_blocked_manifests_pass_integration(self):
        self.assertEqual(blocked_main(None), 0)

    def test_valid_temp_manifest_passes_main(self):
        self.assertEqual(blocked_main([self._temp(dict(BASE_BLOCKED))]), 0)

    def test_tampered_blocked_manifest_fails_main(self):
        tampered = dict(BASE_BLOCKED, sharpe=1.5)
        with self.assertRaises(SystemExit):
            blocked_main([self._temp(tampered)])

    def test_missing_manifest_fails_main(self):
        with self.assertRaises(SystemExit):
            blocked_main([ROOT / "scripts" / "does_not_exist.json"])


if __name__ == "__main__":
    unittest.main()
