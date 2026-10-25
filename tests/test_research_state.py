import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from validate_research_state import (  # noqa: E402
    FROZEN_GRID_SHA,
    validate_artifact_data,
    validate_confirmatory,
)

FROZEN_DIGEST = "6be218bc84bf118cf67c238ad1c13ef1e445658db3b1346cd64ccaccc7aa5f07"

BASE = {
    "schema_version": "1.0",
    "experiment_id": "FVD-DISPERSION-V1",
    "run_id": "run-2026-01-01",
    "status": "BLOCKED_DATA_GATE",
    "backtest_completed": False,
    "performance_metrics_computed": False,
    "historical_point_in_time_market_cap_gate": "BLOCKED",
    "grid_config_sha256": FROZEN_DIGEST,
    "output_artifacts": [],
    "caveats": ["no performance claim"],
    "started_at_utc": "2026-01-01T00:00:00Z",
    "date_utc": "2026-01-01",
}


class ResearchStateValidatorTests(unittest.TestCase):
    def test_valid_manifest_passes(self):
        self.assertEqual(validate_artifact_data(dict(BASE), "run_manifest.json"), [])

    def test_committed_manifests_pass(self):
        import json
        for name in ("run_manifest.json", "exploratory_run_manifest_2026-10-24.json",
                      "exploratory_run_manifest_2026-10-25.json"):
            data = json.loads((ROOT / "research_state" / name).read_text())
            self.assertEqual(validate_artifact_data(data, name), [], msg=name)

    def test_missing_top_key_fails(self):
        bad = dict(BASE)
        del bad["schema_version"]
        errors = validate_artifact_data(bad, "run_manifest.json")
        self.assertTrue(any("schema_version" in e for e in errors))

    def test_missing_state_key_fails(self):
        bad = dict(BASE)
        del bad["backtest_completed"]
        errors = validate_artifact_data(bad, "run_manifest.json")
        self.assertTrue(any("backtest_completed" in e for e in errors))

    def test_state_key_must_be_false(self):
        bad = dict(BASE, backtest_completed=True)
        errors = validate_artifact_data(bad, "run_manifest.json")
        self.assertTrue(any("backtest_completed" in e for e in errors))

    def test_non_object_fails(self):
        errors = validate_artifact_data([], "run_manifest.json")
        self.assertTrue(errors)

    def test_unknown_status_fails(self):
        bad = dict(BASE, status="PROFITABLE")
        errors = validate_artifact_data(bad, "run_manifest.json")
        self.assertTrue(any("PROFITABLE" in e for e in errors))

    def test_gate_must_be_blocked(self):
        bad = dict(BASE, historical_point_in_time_market_cap_gate="PASS")
        errors = validate_artifact_data(bad, "run_manifest.json")
        self.assertTrue(any("PASS" in e for e in errors))

    def test_non_utc_timestamp_fails(self):
        bad = dict(BASE, started_at_utc="2026-01-01T00:00:00")
        errors = validate_artifact_data(bad, "run_manifest.json")
        self.assertTrue(any("started_at_utc" in e for e in errors))

    def test_bad_date_utc_format_fails(self):
        bad = dict(BASE, date_utc="2026/01/01")
        errors = validate_artifact_data(bad, "run_manifest.json")
        self.assertTrue(any("date_utc" in e for e in errors))

    def test_bad_sha256_fails(self):
        bad = dict(BASE, grid_config_sha256="not-a-sha256")
        errors = validate_artifact_data(bad, "run_manifest.json")
        self.assertTrue(any("grid_config_sha256" in e for e in errors))

    def test_confirmatory_passes_when_frozen(self):
        self.assertEqual(validate_confirmatory(dict(BASE)), [])

    def test_confirmatory_status_must_be_blocked(self):
        bad = dict(BASE, status="NOT_RUN")
        errors = validate_confirmatory(bad)
        self.assertTrue(any("BLOCKED_DATA_GATE" in e for e in errors))

    def test_confirmatory_gate_must_be_blocked(self):
        bad = dict(BASE, historical_point_in_time_market_cap_gate="NOT_VERIFIED")
        errors = validate_confirmatory(bad)
        self.assertTrue(any("BLOCKED" in e for e in errors))

    def test_confirmatory_grid_hash_must_be_frozen(self):
        bad = dict(BASE, grid_config_sha256="0" * 64)
        errors = validate_confirmatory(bad)
        self.assertTrue(any("grid" in e for e in errors))

    def test_exploratory_status_permitted(self):
        bad = dict(BASE, status="EXPLORATORY_ONLY")
        errors = validate_artifact_data(bad, "exploratory_run_manifest_2026-10-24.json")
        self.assertEqual(errors, [])

    def test_inconclusive_status_permitted(self):
        bad = dict(BASE, status="INCONCLUSIVE")
        errors = validate_artifact_data(bad, "exploratory_run_manifest_2026-10-24.json")
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()